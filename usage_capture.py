#!/usr/bin/env python3
"""Anchor usage-capture pipeline — the ONE honest cost trail (Honest Telemetry W4).

Every interactive ConPTY session and every one-shot ``job_runner`` job leaves a
machine-verified cost trail through THIS module:

  UUID captured AT LAUNCH (never mtime-guessed, ``terminal_session`` stores it on
  the registry record) → the **sum-over-message parser** against the pinned W1
  sidecar fixture (``tests/fixtures/sidecar/``) → the append-only, idempotent
  :mod:`usage_ledger` (keyed by ``(engine_session_uuid, message_uuid/line-hash)``)
  → an **eager finalize** on EVERY session end path (kill / close-park / drain /
  finish / reconcile-dead) that copies the usage snapshot into Anchor's own
  durable ``.anchor/`` store as a RUN-provenance cost record.

Locked contracts this cites (see ``NORTH-STAR-AMENDMENT.md`` + ``W1-GROUND-TRUTH.md``
§1):

  - **Tripwire severity (LOCKED).** A sidecar that is PRESENT but unparseable, or
    that yields zero usage from a session that demonstrably had message lines, is a
    CORRECTNESS failure → an atomic ``state='capture-failed'`` record carrying the
    parse-error class. NEVER a measured-$0 record, NEVER a silent ``unmeasured``.
    Sidecar ABSENT/pruned is the ONLY expected-environmental leg → ``unmeasured
    (sidecar-pruned)``. Capture NEVER halts the session lifecycle.
  - **No-own-pricing-table (LOCKED).** Tokens + time are the measured facts; ``$``
    is 0.0 on the interactive path (the per-message sidecar carries no ``costUSD``)
    and is shown ONLY when the engine itself reported it. Anchor computes no dollar
    figure from a pricing table of its own (one exception: the steward cockpit's
    labeled ChatGPT estimate, NORTH-STAR-AMENDMENT.md rider of 2026-09-25).
  - **defer-and-badge (LOCKED).** Pre-feature sessions are never retro-attributed:
    a session with no captured engine UUID finalizes to ``state='uncorrelated'``
    (an ``unmeasured`` reason), never a guessed total.
  - **DEDUP by ``message.id`` (W1 load-bearing finding).** A single assistant turn
    can span >1 JSONL line sharing one ``message.id``, each repeating the identical
    usage block; the ledger key collapses them so a naive sum never double-counts.

Fail-closed by construction: the sidecar root is resolved through
:func:`paths.sidecar_root`, which RAISES in any hermetic (test / healthcheck /
redirected-data) context unless ``ANCHOR_SIDECAR_DIR`` is explicitly pointed at a
fixture/temp dir — so this pipeline is physically unable to open a real user's
``~/.claude`` store under test. Stdlib only. No third-party imports.
"""

import calendar
import io
import json
import re
import os
import time
from datetime import datetime
from pathlib import Path

import paths as _paths
import session_registry as _reg
import effort_history as _eh
import usage_ledger as _ul
import usage_index as _ui

# ── Usage states (an ENUM, never free text — the rollup renders by these) ─────
STATE_MEASURED = "measured"
#: A resume/engine-switch segment whose upstream parent segment is not present in
#: the local store (so this file's totals are only PART of the whole session).
STATE_PARTIAL = "partial-resumed-elsewhere"
STATE_UNMEASURED = "unmeasured"
STATE_CAPTURE_FAILED = "capture-failed"

# ── Reasons (an ENUM keyed to the finalize/tripwire model) ────────────────────
#: capture-failed reasons (CORRECTNESS — RED in the healthcheck, W7).
REASON_PARSE_ERROR = "parse-error"
REASON_ZERO_USAGE = "zero-usage-despite-message-lines"
#: unmeasured reasons (environmental / honest, NOT red).
REASON_SIDECAR_PRUNED = "sidecar-pruned"
REASON_UNCORRELATED = "uncorrelated"
REASON_SIDECAR_UNAVAILABLE = "sidecar-root-unavailable"
REASON_EMPTY_SIDECAR = "empty-sidecar"
REASON_PRE_FEATURE = "pre-feature"
REASON_GEMINI_SEGMENT = "gemini-segment"
#: Grok interactive path: no Claude-shaped JSONL under ~/.claude; wall-clock only.
REASON_GROK_NO_SIDECAR = "grok-no-claude-sidecar"

#: The ``kind`` marker on the effort pointer-record a finalize writes (mirrors the
#: W2 durability-substrate test's RUN cost record shape).
RUN_COST_KIND = "run-cost"
RUN_COST_SOURCE = "run"


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _zero_totals() -> dict:
    return {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "total_all_classes": 0,
        "input_plus_output": 0,
    }


def _sum_usage(usage_dicts) -> dict:
    """Sum a collection of per-message usage dicts into the roll-up totals.

    Each dict carries the four token classes; the two derived roll-ups
    (``total_all_classes`` = every class summed, ``input_plus_output`` = the
    classic pair) are computed so the pipeline can pick its accounting.
    """
    t = _zero_totals()
    for u in usage_dicts:
        t["input_tokens"] += _int(u.get("input_tokens"))
        t["cache_creation_input_tokens"] += _int(
            u.get("cache_creation_input_tokens"))
        t["cache_read_input_tokens"] += _int(u.get("cache_read_input_tokens"))
        t["output_tokens"] += _int(u.get("output_tokens"))
    t["total_all_classes"] = (t["input_tokens"]
                              + t["cache_creation_input_tokens"]
                              + t["cache_read_input_tokens"]
                              + t["output_tokens"])
    t["input_plus_output"] = t["input_tokens"] + t["output_tokens"]
    return t


def _parse_ts(ts):
    """Parse an ISO-8601 sidecar timestamp to an aware datetime, or None."""
    if not ts:
        return None
    try:
        s = str(ts)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _duration_ms(timestamps) -> int:
    """First-record → last-record wall-clock duration in ms (0 if < 2 stamps)."""
    dts = [d for d in (_parse_ts(t) for t in timestamps) if d is not None]
    if len(dts) < 2:
        return 0
    delta = max(dts) - min(dts)
    return int(round(delta.total_seconds() * 1000))


# ══════════════════════════════════════════════════════════════════════════════
# The sum-over-message parser + capture-failed classifier
# ══════════════════════════════════════════════════════════════════════════════

class ParseResult(dict):
    """A parse result (a plain dict; a class only so callers can `isinstance`)."""


def _result(state, reason, session_uuid, totals, entries, duration_ms,
            assistant_lines, unique_message_ids, has_message_lines):
    return ParseResult({
        "state": state,
        "reason": reason,
        "session_uuid": session_uuid or "",
        "token_totals": totals,
        "entries": entries,
        "duration_ms": duration_ms,
        "assistant_record_lines": assistant_lines,
        "unique_message_ids": unique_message_ids,
        "has_message_lines": has_message_lines,
    })


def parse_sidecar_text(text, engine_session_uuid=None) -> ParseResult:
    """Parse a Claude sidecar JSONL body → a classified :class:`ParseResult`.

    The sum-over-message parser (W4): sum the per-message usage blocks of the
    assistant records, **deduped by ``message.id``** so a tool-use turn written
    across multiple JSONL lines sharing one id is counted ONCE (the W1 load-bearing
    finding). Classification, per the locked tripwire severity:

    - one JSON line RAISES on parse → ``capture-failed`` (``parse-error``);
    - message lines present but every usage block missing/zero →
      ``capture-failed`` (``zero-usage-despite-message-lines``);
    - message lines present with ≥1 nonzero usage block → ``measured`` with the
      deduped token totals + first→last duration;
    - no message lines at all → ``unmeasured`` (``empty-sidecar``).

    NEVER raises — a malformed line is classified, not propagated. Pure.
    """
    session_uuid = engine_session_uuid or ""
    by_msg = {}                 # message.id → deduped usage entry (first wins)
    order = []                  # stable first-seen order of message ids
    timestamps = []
    assistant_lines = 0
    has_successful_assistant_lines = False
    last_model = None

    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            # PRESENT-but-unparseable → capture-failed (RED), regardless of
            # whether a message line was seen first.
            return _result(STATE_CAPTURE_FAILED, REASON_PARSE_ERROR,
                           session_uuid, _zero_totals(), [], 0,
                           assistant_lines, len(by_msg), True)
        if not isinstance(obj, dict):
            continue
        typ = obj.get("type")
        if typ == "summary":
            continue
        if typ in ("user", "assistant"):
            if not session_uuid:
                session_uuid = obj.get("sessionId") or ""
            ts = obj.get("timestamp")
            if ts:
                timestamps.append(ts)
        if typ == "assistant":
            assistant_lines += 1
            if not obj.get("isApiErrorMessage"):
                has_successful_assistant_lines = True
            msg = obj.get("message") or {}
            mid = msg.get("id")
            usage = msg.get("usage")
            if isinstance(msg.get("model"), str) and msg["model"]:
                last_model = msg["model"]
            if mid is not None and isinstance(usage, dict):
                if mid not in by_msg:  # dedup: identical repeat lines collapse
                    order.append(mid)
                    by_msg[mid] = {
                        "key": _ul.entry_key(session_uuid, message_uuid=mid),
                        "message_uuid": mid,
                        "input_tokens": _int(usage.get("input_tokens")),
                        "cache_creation_input_tokens": _int(
                            usage.get("cache_creation_input_tokens")),
                        "cache_read_input_tokens": _int(
                            usage.get("cache_read_input_tokens")),
                        "output_tokens": _int(usage.get("output_tokens")),
                        "timestamp": obj.get("timestamp"),
                    }

    entries = [by_msg[m] for m in order]
    totals = _sum_usage(entries)

    def _with_model(res):
        res["model"] = last_model
        return res

    if not has_successful_assistant_lines:
        # A present-but-turnless file (only local commands, API errors, or empty). Honest
        # unmeasured — NOT capture-failed (there were no successful turns to measure).
        return _with_model(_result(STATE_UNMEASURED, REASON_EMPTY_SIDECAR, session_uuid,
                                   totals, [], 0, assistant_lines, 0, False))
    if totals["total_all_classes"] <= 0:
        # Successful assistant lines present but zero usage → CORRECTNESS failure.
        return _with_model(_result(STATE_CAPTURE_FAILED, REASON_ZERO_USAGE, session_uuid,
                                   _zero_totals(), [], 0, assistant_lines, len(by_msg), True))

    return _with_model(_result(STATE_MEASURED, None, session_uuid, totals, entries,
                               _duration_ms(timestamps), assistant_lines, len(by_msg), True))


def parse_sidecar_file(path, engine_session_uuid=None) -> ParseResult:
    """Read + parse a sidecar file. A missing file is NOT this function's concern
    (the caller resolves presence); an unreadable one is ``capture-failed``."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _result(STATE_CAPTURE_FAILED, REASON_PARSE_ERROR,
                       engine_session_uuid or "", _zero_totals(), [], 0,
                       0, 0, False)
    return parse_sidecar_text(text, engine_session_uuid=engine_session_uuid)


# ══════════════════════════════════════════════════════════════════════════════
# Sidecar location (fail-closed) + ledger ingestion
# ══════════════════════════════════════════════════════════════════════════════

def locate_sidecar(engine_session_uuid, root=None):
    """Resolve the ``<uuid>.jsonl`` sidecar path for an engine session, or None.

    The store layout is ``<root>/<slug>/<uuid>.jsonl``; a fixture/temp root may
    also place ``<root>/<uuid>.jsonl`` directly. Searches ``<uuid>.jsonl`` at the
    root and one level down (the slug dirs). ``root`` defaults to the FAIL-CLOSED
    :func:`paths.sidecar_root` — which RAISES in a hermetic context unless
    ``ANCHOR_SIDECAR_DIR`` is set, so this never touches a real ``~/.claude`` store
    under test. Returns None when no matching file exists.
    """
    if not engine_session_uuid:
        return None
    base = Path(root) if root is not None else _paths.sidecar_root()
    name = "%s.jsonl" % (engine_session_uuid,)
    direct = base / name
    if direct.exists():
        return direct
    try:
        for child in base.iterdir():
            if child.is_dir():
                cand = child / name
                if cand.exists():
                    return cand
    except OSError:
        return None
    return None


def ingest_sidecar(engine_session_uuid, path_or_text, is_text=False) -> ParseResult:
    """Parse a sidecar and APPEND its per-message usage to the durable ledger.

    Idempotent by construction: the ledger dedups by ``(engine_session_uuid,
    message_uuid/line-hash)``, so re-ingesting the SAME file — or a resume of the
    same session — never double-counts (the W4 switch-engine invariant). Only a
    ``measured`` parse contributes ledger entries; a capture-failed/unmeasured
    parse appends nothing (there is no honest usage to ledger). Returns the
    :class:`ParseResult`.
    """
    if is_text:
        res = parse_sidecar_text(path_or_text,
                                 engine_session_uuid=engine_session_uuid)
    else:
        res = parse_sidecar_file(path_or_text,
                                 engine_session_uuid=engine_session_uuid)
    if res.get("state") == STATE_MEASURED and res.get("entries"):
        try:
            _ul.append_entries(engine_session_uuid, res["entries"])
        except Exception:
            pass
    return res


def combined_totals(engine_session_uuids) -> dict:
    """Sum the DEDUPED ledger token totals across one or more engine sessions.

    Each engine session is a distinct ledger doc (distinct message ids), so the
    combined total is the sum of each doc's deduped entries — the W4 switch-engine
    invariant's ``total = A-part + B-part counted once``. Reads the ledger only
    (authoritative + idempotent); never re-parses. Returns the roll-up totals.
    """
    all_entries = []
    for u in (engine_session_uuids or []):
        if not u:
            continue
        try:
            all_entries.extend(_ul.ledger_entries(u))
        except Exception:
            continue
    return _sum_usage(all_entries)


def _cost_block(totals, duration_ms) -> dict:
    """The RUN cost record's ``cost`` block. ``$`` is 0.0 on the interactive path
    (no ``costUSD`` in the per-message sidecar; no own pricing table)."""
    return {
        "input_tokens": totals["input_tokens"],
        "cache_creation_input_tokens": totals["cache_creation_input_tokens"],
        "cache_read_input_tokens": totals["cache_read_input_tokens"],
        "output_tokens": totals["output_tokens"],
        # Both roll-ups are carried so the rollup (W5) can pick its accounting;
        # ``total_tokens`` is the rollup's canonical field (== total_all_classes).
        "total_all_classes": totals["total_all_classes"],
        "total_tokens": totals["total_all_classes"],
        "input_plus_output": totals["input_plus_output"],
        "duration_ms": int(duration_ms or 0),
        "total_cost_usd": 0.0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# The eager finalize — one RUN cost record per session, on every end path
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_folder(project_id):
    try:
        import rnd_registry as _rnd
        proj = _rnd.get_project(project_id)
        return (proj or {}).get("folder_path", "") or ""
    except Exception:
        return ""


def _engine_uuids_of(record) -> list:
    """The ordered list of engine session UUIDs a managed session touched.

    Prefers the append-only ``engine_session_uuids`` history (populated at launch
    and on every engine switch); falls back to the single ``engine_session_uuid``.
    """
    if not isinstance(record, dict):
        return []
    lst = record.get("engine_session_uuids")
    if isinstance(lst, (list, tuple)):
        out = [str(u) for u in lst if u]
        if out:
            return out
    one = record.get("engine_session_uuid")
    return [str(one)] if one else []


def finalize_session_usage(session_id, project_id=None, lane=None, record=None,
                           folder_path=None, actor=None) -> dict:
    """Finalize a managed session's usage ONCE — the eager end-path capture (W4).

    Called from EVERY end path (kill / close-park / drain / finish /
    reconcile-dead). The ``cost_final`` compare-and-set latch (W2) makes it
    idempotent across racing end paths: exactly one caller writes the session's
    single RUN cost record; every later call is a clean no-op. NEVER raises and
    NEVER halts the session lifecycle — a capture failure produces an honest
    ``capture-failed`` record (not a crash), a fail-closed sidecar root (hermetic
    test with no fixture dir) degrades to ``unmeasured``.

    Outcomes (each stamps ``usage_state``/``usage_reason`` on the registry record):

    - **measured** — writes ONE ``run-cost`` effort pointer-record whose ``cost``
      block is the deduped token totals + first→last duration ($ = 0.0);
    - **capture-failed** — writes ONE ``run-cost`` record with ``cost=None`` and
      the parse-error class (never a measured-$0 record, never silent unmeasured);
    - **unmeasured** — writes NO effort cost record (nothing to measure honestly);
      only the registry ``usage_state`` is stamped (``uncorrelated`` when no engine
      UUID was captured, ``sidecar-pruned`` when the file is gone).

    Returns ``{"finalized": bool, "state": <state>, "reason": <reason|None>,
    "cost": <block|None>, "won": bool}``.
    """
    out = {"finalized": False, "state": None, "reason": None,
           "cost": None, "won": False}
    if not session_id:
        return out
    try:
        rec = record if record is not None else _reg.get_session(session_id)
    except Exception:
        rec = None
    if not isinstance(rec, dict):
        return out

    # The finalize-once latch (W2). Only the winner writes the cost record.
    try:
        won = _reg.finalize_cost_once(session_id)
    except Exception:
        won = False
    out["won"] = won
    if not won:
        out["reason"] = "already-finalized"
        return out
    try:
        ingest_receipts()      # the seats this session's skills ran (S3)
    except Exception:
        pass

    if project_id is None:
        project_id = rec.get("project_id") or None
    if lane is None:
        lane = rec.get("lane", "") or ""
    if folder_path is None:
        folder_path = _resolve_folder(project_id)

    uuids = _engine_uuids_of(rec)

    # Wall-clock for unmeasured sessions (Grok / no-sidecar): never invents tokens.
    duration_ms_observed = _session_wall_clock_ms(rec)

    # 1) No engine UUID was captured at launch → honest UNCORRELATED (defer-and-
    #    badge). Never a guessed total. Grok wall-clock-only row is opt-in below
    #    when UUID was pinned but Claude-shaped sidecar is absent.
    if not uuids:
        backend = str(rec.get("backend") or "").lower()
        reason = (REASON_GROK_NO_SIDECAR if backend == "grok"
                  else REASON_UNCORRELATED)
        _stamp(session_id, STATE_UNMEASURED, reason)
        if backend == "grok":
            _write_run_cost_wall_only(
                folder_path, project_id, lane, session_id, duration_ms_observed,
                reason)
        out.update(finalized=True, state=STATE_UNMEASURED, reason=reason)
        return out

    # 2) Ingest every segment's sidecar into the ledger + classify. A fail-closed
    #    sidecar root (hermetic, no fixture dir) is caught → unmeasured, not a
    #    crash. Duration is summed across segments (the switch-engine combined).
    states = []
    reasons = []
    duration_ms = 0
    located_any = False
    for u in uuids:
        try:
            path = locate_sidecar(u)
        except _paths.SidecarRootUnavailable:
            path = None
            reasons.append(REASON_SIDECAR_UNAVAILABLE)
            states.append(STATE_UNMEASURED)
            continue
        except Exception:
            path = None
        if path is None:
            states.append(STATE_UNMEASURED)
            reasons.append(REASON_SIDECAR_PRUNED)
            continue
        located_any = True
        res = ingest_sidecar(u, path)
        states.append(res.get("state"))
        if res.get("reason"):
            reasons.append(res.get("reason"))
        duration_ms += int(res.get("duration_ms", 0) or 0)

    # 3) Classify the SESSION over its segments (capture-failed dominates —
    #    tripwire severity; else measured if any segment measured; else unmeasured).
    if STATE_CAPTURE_FAILED in states:
        reason = next((r for r in reasons
                       if r in (REASON_PARSE_ERROR, REASON_ZERO_USAGE)),
                      REASON_PARSE_ERROR)
        _write_capture_failed(folder_path, project_id, lane, session_id,
                              uuids[0], reason)
        _stamp(session_id, STATE_CAPTURE_FAILED, reason)
        out.update(finalized=True, state=STATE_CAPTURE_FAILED, reason=reason)
        return out

    if STATE_MEASURED in states:
        totals = combined_totals(uuids)
        cost = _cost_block(totals, duration_ms)
        _write_run_cost(folder_path, project_id, lane, session_id, uuids[0],
                        cost, STATE_MEASURED)
        _stamp(session_id, STATE_MEASURED, None)
        out.update(finalized=True, state=STATE_MEASURED, cost=cost)
        return out

    # Unmeasured — no honest token usage. Stamp the reason (pruned / unavailable).
    # For Grok (or when backend=grok and Claude sidecar missing), write wall-clock
    # only so project rollups show time; never invent tokens/$.
    reason = (REASON_SIDECAR_PRUNED if located_any is False
              and REASON_SIDECAR_PRUNED in reasons else
              (reasons[0] if reasons else REASON_SIDECAR_PRUNED))
    backend = str(rec.get("backend") or "").lower()
    if backend == "grok" and reason in (
            REASON_SIDECAR_PRUNED, REASON_SIDECAR_UNAVAILABLE, REASON_EMPTY_SIDECAR):
        reason = REASON_GROK_NO_SIDECAR
    _stamp(session_id, STATE_UNMEASURED, reason)
    if backend == "grok":
        wall = duration_ms if duration_ms > 0 else duration_ms_observed
        _write_run_cost_wall_only(
            folder_path, project_id, lane, session_id, wall, reason,
            engine_session_uuid=(uuids[0] if uuids else ""))
    out.update(finalized=True, state=STATE_UNMEASURED, reason=reason)
    return out


def _session_wall_clock_ms(record) -> int:
    """Best-effort session wall clock from registry timestamps (never tokens)."""
    if not isinstance(record, dict):
        return 0
    try:
        created = float(record.get("created_at") or 0)
    except (TypeError, ValueError):
        created = 0.0
    end = None
    for key in ("finished_at", "updated_at", "ended_at"):
        try:
            v = float(record.get(key) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            end = v
            break
    if not created:
        return 0
    if end is None or end < created:
        import time as _time
        end = _time.time()
    return max(0, int((end - created) * 1000))


def _write_run_cost_wall_only(folder_path, project_id, lane, session_id,
                              duration_ms, usage_reason,
                              engine_session_uuid="") -> None:
    """Write a RUN cost row with tokens/$ = 0 and wall-clock only (unmeasured).

    Honesty: total_tokens and total_cost_usd stay 0 — never fabricates spend.
    Enables project_effort_rollup to show session time for Grok / uncorrelated.
    """
    if not folder_path or not project_id or not duration_ms:
        return
    cost = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "total_all_classes": 0,
        "total_tokens": 0,
        "input_plus_output": 0,
        "duration_ms": int(duration_ms or 0),
        "total_cost_usd": 0.0,
        "usage_state": STATE_UNMEASURED,
        "usage_reason": usage_reason or "",
    }
    _write_run_cost(folder_path, project_id, lane, session_id,
                    engine_session_uuid or "", cost, STATE_UNMEASURED)


def _write_run_cost(folder_path, project_id, lane, session_id,
                    engine_session_uuid, cost, usage_state) -> None:
    """Write the session's single MEASURED RUN cost pointer-record (idempotent by
    the ``run-cost-<sid>`` job id). Best-effort — never breaks the end path."""
    if not folder_path or not project_id:
        return
    try:
        store_lane = _eh._resolve_subdir(lane or "")
        _eh.record_effort(
            folder_path, project_id, store_lane, "run-cost-%s" % (session_id,),
            extra={
                "source": RUN_COST_SOURCE,
                "kind": RUN_COST_KIND,
                "provenance": "run",
                "session_id": session_id,
                "engine_session_uuid": engine_session_uuid or "",
                "usage_state": usage_state,
                "cost": cost,
            })
    except Exception:
        pass


def _write_capture_failed(folder_path, project_id, lane, session_id,
                          engine_session_uuid, reason) -> None:
    """Write the session's atomic CAPTURE-FAILED record (``cost=None``, carrying
    the parse-error class) — never a measured-$0, never a silent unmeasured."""
    if not folder_path or not project_id:
        return
    try:
        store_lane = _eh._resolve_subdir(lane or "")
        _eh.record_effort(
            folder_path, project_id, store_lane, "run-cost-%s" % (session_id,),
            extra={
                "source": RUN_COST_SOURCE,
                "kind": RUN_COST_KIND,
                "provenance": "run",
                "session_id": session_id,
                "engine_session_uuid": engine_session_uuid or "",
                "usage_state": STATE_CAPTURE_FAILED,
                "usage_reason": reason,
                "cost": None,
            })
    except Exception:
        pass


def _stamp(session_id, usage_state, usage_reason) -> None:
    """Stamp the terminal usage state onto the registry record (best-effort)."""
    try:
        _reg.update_session(session_id, usage_state=usage_state,
                            usage_reason=(usage_reason or ""))
    except Exception:
        pass


def snapshot_session_usage(session_id, record=None) -> dict:
    """Piggyback a NON-finalizing usage snapshot onto the 120s autosave heartbeat.

    Ingests the session's current sidecar segments into the durable ledger WITHOUT
    flipping the ``cost_final`` latch — so a weeks-later reconcile of a crashed
    session reads Anchor's own accumulated snapshot rather than the prunable home
    store, yet the eager end-path :func:`finalize_session_usage` remains the sole
    writer of the RUN cost record. Best-effort, never raises, a no-op when the
    sidecar root is fail-closed (hermetic, no fixture dir). Returns
    ``{"ingested": int}``.
    """
    out = {"ingested": 0}
    try:
        rec = record if record is not None else _reg.get_session(session_id)
    except Exception:
        rec = None
    if not isinstance(rec, dict):
        return out
    for u in _engine_uuids_of(rec):
        try:
            path = locate_sidecar(u)
        except _paths.SidecarRootUnavailable:
            return out
        except Exception:
            continue
        if path is None:
            continue
        res = ingest_sidecar(u, path)
        if res.get("state") == STATE_MEASURED:
            out["ingested"] += len(res.get("entries", []))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# job_runner unification — durable-job stream-json usage → the SAME ledger
# ══════════════════════════════════════════════════════════════════════════════

def ingest_job_cost(engine_session_uuid, cost, job_id, record=None) -> int:
    """Route a durable ``job_runner`` job through the attribution seam.

    A finished job with a result envelope carries ``usage`` + ``session_id``
    (the engine session UUID) in its ``cost`` block: its row goes to that
    session's ledger doc (keyed by the ``job_id`` line-hash, so a re-finalize is
    idempotent) and to the project's index. A job that died before any result
    (no envelope, no session) still spawned: it becomes an ``unknown`` row in
    the index (Grok R1 F4). A missing price stays ``None`` (never a priced $0).
    The row carries the project the job ran for — the record's own
    ``project_id``/``folder_path`` when a guarded launch set them, else the
    registered project at or above the folder it ran in; a worktree cwd outside
    that folder joins at the project folder (Grok R1 F2). Best-effort.
    """
    if not job_id:
        return 0
    cost = cost if isinstance(cost, dict) else {}
    inp = _int(cost.get("input_tokens"))
    out = _int(cost.get("output_tokens"))
    rec = record if isinstance(record, dict) else {}
    project_id = rec.get("project_id") or None
    folder_path = rec.get("folder_path") or None
    candidates = [d for d in (rec.get("effort_dir"), rec.get("refinement_dir"),
                              rec.get("cwd"), folder_path) if d]
    if not project_id:
        for d in candidates:
            project_id, folder_path = resolve_project(d)
            if project_id:
                break
    where = next((d for d in candidates if _under(d, folder_path)), folder_path or
                 (candidates[0] if candidates else None))
    receipt = rec.get("model_receipt") if isinstance(rec.get("model_receipt"), dict) else {}
    finished = rec.get("finished_at")
    return ingest_usage(
        engine_session_uuid or None,
        _ul.entry_key(engine_session_uuid or "", line="job:%s" % (job_id,)),
        index_key="job:%s" % (job_id,),
        source=SOURCE_JOB, native_id=job_id,
        tokens=_int(cost.get("total_tokens")) or (inp + out),
        cost_usd=_cost_number(cost.get("total_cost_usd")),
        project_id=project_id, folder_path=folder_path, effort_dir=where,
        cli=rec.get("backend") or None,
        provider_connection_id=(rec.get("provider_connection") or {}).get("id"),
        model=receipt.get("model_served") or receipt.get("model") or None,
        duration_ms=_int(cost.get("duration_ms")),
        usage={"input_tokens": inp, "output_tokens": out,
               "cached_input_tokens": _int(cost.get("cached_input_tokens"))} if cost else None,
        recorded_at=_iso(finished) if isinstance(finished, (int, float)) and not isinstance(finished, bool) else None)


# ── Attribution: the one honest seam (codex-discipline Wave 2 S1) ─────────────
# Every row carries the ids that already exist (project, folder, effort dir,
# engine session, native turn/job id) and an honest state; nothing is priced
# that was not priced. The ledger keeps the row; the per-project index keeps a
# compact copy of the rows the cockpit sums (delegated jobs).
USAGE_MEASURED = STATE_MEASURED   # a recorded charge
USAGE_UNPRICED = "unpriced"       # tokens known, no per-turn price (subscription)
USAGE_UNKNOWN = "unknown"         # a spawn is known, no usage reached us
USAGE_STATES = (USAGE_MEASURED, USAGE_UNPRICED, USAGE_UNKNOWN)

SOURCE_STEWARD_TURN = "steward-turn"
SOURCE_TERMINAL_TURN = "terminal-turn"   # a cockpit workbench (general) turn
SOURCE_JOB = "job"
SOURCE_SUBAGENT = "subagent"             # a child the steward's session spawned (S2)
SOURCE_SEAT = "seat"                     # a trio seat a skill ran (S3)
#: Sources the cockpit sums from the index. Steward and workbench turns stay
#: sourced from cockpit state (history + in-flight), so they are ledger-only.
INDEXED_SOURCES = (SOURCE_JOB, SOURCE_SUBAGENT, SOURCE_SEAT)
#: The index row: what the rollup reads (``scope``/``folder_scope`` are the
#: normalized paths stamped at write time so a poll compares strings and never
#: realpaths 8k rows — Grok R1 F5), plus the ids that lead back to the spawn and
#: its ledger doc (a key is a hash; a row must still name its job or child, and
#: a child its immediate parent).
INDEX_FIELDS = ("key", "source", "native_id", "engine_session_uuid", "folder_path",
                "effort_dir", "scope", "folder_scope", "cli", "model", "model_attested", "tokens",
                "cost_usd", "usage_state", "duration_ms", "recorded_at", "parent_id")


def _iso(unix_seconds) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(unix_seconds)))


def _scope(path):
    """The comparable form of a folder: normcased realpath, or ``None``."""
    if not path:
        return None
    try:
        return os.path.normcase(os.path.realpath(str(path)))
    except (TypeError, ValueError, OSError):
        return None


def _under(path, root) -> bool:
    """``path`` is ``root`` or inside it (both as scopes)."""
    a, b = _scope(path), _scope(root)
    return bool(a and b) and (a == b or a.startswith(b.rstrip(os.sep) + os.sep))


def _cost_number(value):
    """A recorded charge as a float, else ``None`` (missing / not a number / bool)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        return None
    return value


def usage_state_for(tokens, cost_usd) -> str:
    """measured when a positive charge was recorded (whatever the token count —
    Grok R1 F3); unpriced when tokens are known without a price (or a $0 that
    prices nothing); unknown when neither reached us."""
    tokens = _int(tokens)
    cost = _cost_number(cost_usd)
    if cost is not None and cost > 0:
        return USAGE_MEASURED
    if tokens > 0:
        return USAGE_UNPRICED
    return USAGE_UNKNOWN


def resolve_project(folder):
    """``(project_id, folder_path)`` of the registered project at or above
    ``folder`` — the id the cockpit already uses. The nearest (longest)
    registered folder wins; ``(None, None)`` when unregistered. Never raises."""
    target = _scope(folder)
    if not target:
        return (None, None)
    try:
        import rnd_registry as _rr
        best = None
        for project in _rr.list_projects():
            if not isinstance(project, dict):
                continue
            root = project.get("folder_path")
            pid = project.get("id")
            if (not isinstance(root, str) or not root.strip()
                    or not isinstance(pid, str) or not pid):
                continue
            base = _scope(root)
            if not base or (target != base and not target.startswith(base.rstrip(os.sep) + os.sep)):
                continue
            rank = (len(base), pid)
            if (best is None or rank[0] > best[0][0]
                    or (rank[0] == best[0][0] and rank[1] < best[0][1])):
                best = (rank, pid, root)
        if best:
            return (best[1], best[2])
        return _worktree_owner(target)
    except Exception:
        return (None, None)


def _worktree_owner(target):
    """The project of the managed session whose worktree holds ``target`` — a
    job or seat running in a worktree outside the project folder joins the
    project that session belongs to (the S1 rule for guarded worktree jobs)."""
    try:
        import rnd_registry as _rr
        import session_registry as _sr
        for sess in _sr.list_sessions():
            if not isinstance(sess, dict) or not sess.get("project_id"):
                continue
            wp = _scope(sess.get("worktree_path"))
            if wp and (target == wp or target.startswith(wp.rstrip(os.sep) + os.sep)):
                folder = (_rr.get_project(sess["project_id"]) or {}).get("folder_path")
                return (sess["project_id"], folder or None)
    except Exception:
        pass
    return (None, None)


def turn_key(engine_session_uuid, native_id) -> str:
    """The write-once key of a finalized turn: the invocation id when the
    provider gave one, else the cockpit's own ``cli:session:turn`` id."""
    return _ul.entry_key(engine_session_uuid, line="turn:%s" % (native_id,))


def ingest_usage(engine_session_uuid, key, *, source, native_id, tokens,
                 cost_usd=None, project_id=None, folder_path=None, effort_dir=None,
                 cli=None, model=None, duration_ms=0, usage=None, recorded_at=None,
                 index_key=None, parent_id=None, replace=False, attested=None,
                 provider_connection_id=None) -> int:
    """Write ONE attributed usage row: the ledger entry (write-once per key under
    the engine session's doc) and, for an indexed source with a project, the
    compact per-project index row the cockpit reads. A row with no engine
    session (a spawn that died before any result) has no ledger doc to join and
    is written to the index only, as ``unknown``.

    ``index_key`` names the index row independently of the engine session (a
    job is ``job:<job_id>``), so two writers for one spawn — a liveness check
    while the reader still drains, then the finalize with the envelope — land on
    ONE row: the index keeps the first write and upgrades an ``unknown``
    placeholder once usage arrives (Grok R3 F11). ``cost_usd`` ``None`` stays
    ``None`` — a subscription turn is *unpriced*, not $0. Returns the number of
    NEW ledger entries (0 or 1). Best-effort: never raises into a turn or a job.
    """
    if not key:
        return 0
    tokens = _int(tokens)
    cost = _cost_number(cost_usd)
    entry = {
        "key": key, "source": source, "native_id": native_id,
        "engine_session_uuid": str(engine_session_uuid) if engine_session_uuid else None,
        "project_id": project_id or None, "folder_path": folder_path or None,
        "effort_dir": str(effort_dir) if effort_dir else None,
        "scope": _scope(effort_dir), "folder_scope": _scope(folder_path),
        "cli": cli or None, "model": model or None,
        "tokens": tokens, "cost_usd": cost, "usage_state": usage_state_for(tokens, cost),
        "duration_ms": _int(duration_ms),
        "recorded_at": recorded_at if isinstance(recorded_at, str) and recorded_at
        else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "parent_id": parent_id or None,
        "model_attested": None if attested is None else bool(attested),
    }
    if provider_connection_id:
        entry["provider_connection_id"] = provider_connection_id
    if isinstance(usage, dict):
        entry["usage"] = dict(usage)
    added = 0
    if engine_session_uuid:
        try:
            added = (_ul.upsert_entries if replace else _ul.append_entries)(engine_session_uuid, [entry])
        except Exception:
            added = 0
    if entry["project_id"] and source in INDEXED_SOURCES:
        try:
            row = {f: entry[f] for f in INDEX_FIELDS}
            row["key"] = index_key or key
            _ui.append_rows(entry["project_id"], [row])
        except Exception:
            pass
    return added


# ── Children (Wave 2 S2): one write-once row per sub-agent, recorded at the
# parent's turn end (and once at engine start for a resumed steward), under the
# steward's effort; never folded into the parent's own figure.
CODEX_CHILD_DAYS = 3          # day folders walked; an older chain link is invisible (named)
CODEX_PARENT_DAYS = 120       # day folders name-matched for a steward's own rollout (no reads)
_SPAWNED = {}                 # steward rollout path -> {"size": bytes scanned, "ids": [...]}


def codex_sessions_root(env=None):
    """``<CODEX_HOME>/sessions`` — the same rule the cockpit's usage tracker uses."""
    env = env if env is not None else os.environ
    home = env.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(home) / "sessions"


def _codex_header(path):
    """A rollout's first line when it is a ``session_meta``: thread id, parent
    thread id (top-level or in ``source.subagent.thread_spawn``), start time."""
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            first = json.loads(fh.readline() or "null")
    except (OSError, ValueError):
        return None
    if not isinstance(first, dict) or first.get("type") != "session_meta":
        return None
    p = first.get("payload") or {}
    spawn = {}
    src = p.get("source")
    if isinstance(src, dict) and isinstance(src.get("subagent"), dict):
        spawn = src["subagent"].get("thread_spawn") or {}
    return {"thread_id": p.get("id"), "parent": p.get("parent_thread_id") or spawn.get("parent_thread_id"),
            "root": p.get("session_id"), "started": first.get("timestamp")}


def _codex_day_dirs(root, days=CODEX_CHILD_DAYS, now=None):
    now = now if now is not None else time.time()
    out = []
    for back in range(days):
        t = time.gmtime(now - back * 86400)
        d = Path(root) / time.strftime("%Y", t) / time.strftime("%m", t) / time.strftime("%d", t)
        if d.is_dir():
            out.append(d)
    return out


def codex_children(parent_thread_id, root=None, days=CODEX_CHILD_DAYS, now=None):
    """Every rollout thread that belongs to the steward thread ``parent_thread_id``
    in the last ``days`` day folders (first-line reads only): a child names its
    root session in its header (grandchildren too), and an older header without
    one joins by walking its parent chain. A thread seen in two files keeps the
    newest. Items: ``id``, ``path``, ``parent`` (immediate)."""
    if not parent_thread_id:
        return []
    root = Path(root) if root is not None else codex_sessions_root()
    headers = {}
    for d in _codex_day_dirs(root, days, now):
        try:
            names = sorted(d.glob("rollout-*.jsonl"))
        except OSError:
            continue
        for path in names:
            h = _codex_header(path)
            if not h or not h.get("thread_id"):
                continue
            have = headers.get(h["thread_id"])
            if have is None or str(h.get("started") or "") >= str(have[0].get("started") or ""):
                headers[h["thread_id"]] = (h, path)
    out = []
    for tid, (h, path) in headers.items():
        if tid == parent_thread_id or not h.get("parent"):
            continue
        member = h.get("root") == parent_thread_id
        if not member and not h.get("root"):
            parent, seen = h.get("parent"), set()
            while parent and parent != parent_thread_id and parent in headers and parent not in seen:
                seen.add(parent)
                parent = headers[parent][0].get("parent")
            member = parent == parent_thread_id
        if member:
            out.append({"id": tid, "path": str(path), "parent": h.get("parent"), "started": h.get("started")})
    out.sort(key=lambda c: str(c.get("started") or ""))
    return out


def _codex_rollout_path(thread_id, root=None, days=CODEX_PARENT_DAYS, now=None):
    """The rollout file of ``thread_id`` — its id is in the file name, so this is
    a name match over the day folders, newest first, without reading anything."""
    if not thread_id:
        return None
    root = Path(root) if root is not None else codex_sessions_root()
    for d in _codex_day_dirs(root, days, now):
        try:
            hits = sorted(d.glob("rollout-*-%s.jsonl" % thread_id))
        except OSError:
            continue
        if hits:
            return hits[-1]
    return None


def codex_spawned(parent_thread_id, root=None, now=None):
    """The child thread ids the steward's own rollout names when it started
    them (``SubAgentActivity`` items of kind ``started``): every spawn seen,
    whether or not the child's rollout was found. Empty when the steward's
    rollout is not found."""
    path = _codex_rollout_path(parent_thread_id, root, now=now)
    if path is None:
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    cached = _SPAWNED.get(str(path))
    if cached and cached["size"] == size:
        return list(cached["ids"])
    start = cached["size"] if cached and cached["size"] < size else 0
    out = list(cached["ids"]) if start else []
    seen, scanned = set(out), start
    try:
        with io.open(path, "rb") as fh:
            fh.seek(start)
            for raw in fh:                       # only the bytes added since the last pass
                if not raw.endswith(b"\n"):
                    break                        # a line still being written waits for the next pass
                scanned += len(raw)
                if b'"SubAgentActivity"' not in raw or b'"started"' not in raw:
                    continue
                try:
                    ev = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                item = ((ev.get("payload") or {}).get("item") or {}) if isinstance(ev, dict) else {}
                if (isinstance(item, dict) and item.get("type") == "SubAgentActivity"
                        and item.get("kind") == "started" and item.get("agent_thread_id")):
                    tid = str(item["agent_thread_id"])
                    if tid not in seen:
                        seen.add(tid)
                        out.append(tid)
    except OSError:
        return out
    _SPAWNED[str(path)] = {"size": scanned, "ids": list(out)}
    return out


_AGENT_ID_RE = re.compile(r"agentId:\s*([0-9a-f]{8,})")


def claude_spawned(session_uuid, root=None):
    """The agent ids a Claude session's own transcript names when it launched
    them (the Agent tool's result line), whether or not their transcripts
    exist beside it."""
    try:
        main = locate_sidecar(session_uuid, root=root)
    except Exception:
        return []
    if main is None:
        return []
    out, seen = [], set()
    try:
        with io.open(main, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "agentId" not in line or "agent launched" not in line:   # the tool's own line
                    continue
                for m in _AGENT_ID_RE.finditer(line):
                    if m.group(1) not in seen:
                        seen.add(m.group(1))
                        out.append(m.group(1))
    except OSError:
        pass
    return out


def codex_rollout_usage(path):
    """A child thread's whole usage: the last ``token_count`` event's cumulative
    ``total_tokens`` and the model from the first ``turn_context``; no usage →
    tokens 0 (an ``unknown`` child)."""
    tokens, model = 0, None
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                p = ev.get("payload") or {}
                if not isinstance(p, dict):
                    continue
                if ev.get("type") == "turn_context" and model is None:
                    model = p.get("model") or None
                elif ev.get("type") == "event_msg" and p.get("type") == "token_count":
                    totals = (p.get("info") or {}).get("total_token_usage")
                    if isinstance(totals, dict):
                        tokens = _int(totals.get("total_tokens")) or (
                            _int(totals.get("input_tokens")) + _int(totals.get("output_tokens")))
    except OSError:
        pass
    return {"tokens": tokens, "model": model}


def claude_children(session_uuid, root=None):
    """The ``subagents/agent-*.jsonl`` transcripts beside a Claude session's own
    sidecar; empty when the sidecar root is unavailable (hermetic) or there are
    none. Items: ``id`` (agent id), ``path``, ``parent`` (the session)."""
    try:
        main = locate_sidecar(session_uuid, root=root)
    except Exception:
        return []
    if main is None:
        return []
    folder = Path(main).parent / str(session_uuid) / "subagents"
    if not folder.is_dir():
        return []
    return [{"id": p.stem[len("agent-"):], "path": str(p), "parent": str(session_uuid), "started": None}
            for p in sorted(folder.glob("agent-*.jsonl"))]


def claude_agent_usage(path):
    """A Claude child's whole usage and last model, from one pass of the
    ledger's own per-message parser (repeated message ids collapse)."""
    try:
        res = parse_sidecar_text(io.open(path, encoding="utf-8", errors="replace").read())
    except OSError:
        return {"tokens": 0, "model": None}
    return {"tokens": _int((res.get("token_totals") or {}).get("total_all_classes")), "model": res.get("model")}


def _recorded_epoch(stamp):
    try:
        return calendar.timegm(time.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0


def ingest_children(engine_session_uuid, cli, *, project_id=None, folder_path=None,
                    effort_dir=None, codex_root=None, sidecar_root=None, now=None) -> int:
    """One row per child the steward's session spawned, attributed to its effort
    and keyed by steward and child. The row carries the child's CURRENT
    cumulative total: tokens known → ``unpriced`` (no per-token price is recorded
    for either family) under the parent's ledger doc and in the project index,
    both replaced when the total grows (a child recorded while it still ran);
    no usage → index-only ``unknown``, upgraded once usage appears. A child whose
    file has not changed since its row was recorded is not read again. A child
    the steward named but whose file is not in the walk is read by name, else
    rowed ``unknown``: "unknown" counts every spawn seen. Returns the ledger
    rows written. Never raises."""
    if not engine_session_uuid:
        return 0
    try:
        if cli == "chatgpt":
            found, usage_of = codex_children(engine_session_uuid, root=codex_root, now=now), codex_rollout_usage
            spawned = codex_spawned(engine_session_uuid, root=codex_root, now=now)
        elif cli == "claude":
            found, usage_of = claude_children(engine_session_uuid, root=sidecar_root), claude_agent_usage
            spawned = claude_spawned(engine_session_uuid, root=sidecar_root)
        else:
            return 0
    except Exception:
        return 0
    known = {}
    if project_id:
        try:
            known = {r.get("key"): r for r in _ui.load_rows(project_id)}
        except Exception:
            known = {}
    try:      # the ledger's own child rows: the comparison when no index row exists (Grok S2 F9)
        ledgered = {e.get("key"): e for e in _ul.load_ledger(engine_session_uuid)["entries"].values()
                    if e.get("source") == SOURCE_SUBAGENT}
    except Exception:
        ledgered = {}
    written = 0
    for child in found:
        key = "child:%s:%s" % (engine_session_uuid, child["id"])
        have = known.get(key) or ledgered.get(_ul.entry_key(engine_session_uuid, line=key))
        if have is not None and have.get("usage_state") != USAGE_UNKNOWN:
            try:
                unchanged = int(os.path.getmtime(child["path"])) <= _recorded_epoch(have.get("recorded_at"))
            except OSError:
                unchanged = True
            if unchanged:
                continue
        try:
            u = usage_of(child["path"])
        except Exception:
            u = {"tokens": 0, "model": None}
        tokens = _int(u.get("tokens"))
        if have is not None and tokens <= _int(have.get("tokens")):
            continue                                   # nothing grew; the row stands
        written += ingest_usage(
            engine_session_uuid if tokens > 0 else None,
            _ul.entry_key(engine_session_uuid, line=key), index_key=key, replace=True,
            source=SOURCE_SUBAGENT, native_id=child["id"], tokens=tokens, cost_usd=None,
            project_id=project_id, folder_path=folder_path, effort_dir=effort_dir,
            cli=cli, model=u.get("model"), parent_id=child.get("parent"))
    found_ids = {c["id"] for c in found}
    for tid in spawned:
        if tid in found_ids:
            continue
        key = "child:%s:%s" % (engine_session_uuid, tid)
        have = known.get(key) or ledgered.get(_ul.entry_key(engine_session_uuid, line=key))
        if have is not None and have.get("usage_state") != USAGE_UNKNOWN:
            continue                           # a real row stands; only a placeholder is re-tried
        tokens, model = 0, None
        if cli == "chatgpt":
            path = _codex_rollout_path(tid, root=codex_root, now=now)
            if path is not None:
                try:
                    u = codex_rollout_usage(path)
                    tokens, model = _int(u.get("tokens")), u.get("model")
                except Exception:
                    tokens, model = 0, None
        if have is not None and tokens <= 0:
            continue                           # still nothing to read; the placeholder stands
        written += ingest_usage(
            engine_session_uuid if tokens > 0 else None,
            _ul.entry_key(engine_session_uuid, line=key), index_key=key,
            source=SOURCE_SUBAGENT, native_id=tid, tokens=tokens, cost_usd=None,
            project_id=project_id, folder_path=folder_path, effort_dir=effort_dir,
            cli=cli, model=model, parent_id=engine_session_uuid)
    return written


# ── Ids into children + seat receipts (Wave 2 S3) ────────────────────────────
# A child Anchor spawns inherits the ids the cockpit already has, by environment
# name; a trio seat any skill runs drops one receipt file (the dispatcher's
# sink) into ``ANCHOR_RECEIPTS_DIR``; the sweep below turns each into one row.
ENV_PROJECT = "ANCHOR_PROJECT_ID"
ENV_EFFORT = "ANCHOR_EFFORT_DIR"
ENV_JOB = "ANCHOR_JOB_ID"
ENV_SESSION = "ANCHOR_SESSION_ID"
ENV_RECEIPTS = "ANCHOR_RECEIPTS_DIR"
_UUID_RE = None


def receipts_dir() -> Path:
    """Where trio seats drop their receipts (``.anchor/receipts/``). Not created."""
    return _paths.data_dir() / ".anchor" / "receipts"


def attribution_env(project_id=None, effort_dir=None, job_id=None, session_id=None,
                    folder_path=None) -> dict:
    """The ids a child inherits: project, effort dir, the job or the engine
    session that spawned it, and where to drop receipts. Only known ids are
    set; a missing project is resolved from the folder at ingest, not here."""
    env = {ENV_RECEIPTS: str(receipts_dir())}
    where = effort_dir or folder_path
    if project_id:
        env[ENV_PROJECT] = str(project_id)
    if where:
        env[ENV_EFFORT] = str(where)
    if job_id:
        env[ENV_JOB] = str(job_id)
    if session_id:
        env[ENV_SESSION] = str(session_id)
    return env


def _uuid_like(value) -> bool:
    global _UUID_RE
    if _UUID_RE is None:
        import re as _re
        _UUID_RE = _re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
    return isinstance(value, str) and bool(_UUID_RE.fullmatch(value))


def _seat_tokens(usage) -> int:
    """A seat's token total from its usage block: ``total_tokens`` when the CLI
    reports one, else the additive classes summed — input, output, cache
    creation, cache read. Codex's ``cached_input_tokens`` and
    ``reasoning_output_tokens`` are subsets of input/output (the S1 job and S2
    child rules count them once too)."""
    if not isinstance(usage, dict):
        return 0
    if _int(usage.get("total_tokens")):
        return _int(usage.get("total_tokens"))
    return sum(_int(usage.get(k)) for k in ("input_tokens", "output_tokens",
                                            "cache_creation_input_tokens", "cache_read_input_tokens"))


def _owned_sessions(project_id) -> set:
    """Native sessions the project index already counts as a job (its engine
    session) or as a steward's child (its native id): a seat on one of these is
    the same process seen again."""
    try:
        out = set()
        for row in _ui.load_rows(project_id):
            if row.get("source") == SOURCE_JOB and row.get("engine_session_uuid"):
                out.add(row["engine_session_uuid"])
            elif row.get("source") == SOURCE_SUBAGENT and row.get("native_id"):
                out.add(row["native_id"])
        return out
    except Exception:
        return set()


def _steward_session_for(effort_dir):
    """The engine session the cockpit state holds for ``effort_dir`` (the
    steward's own key), so any sweep can name a seat's parent. ``None`` when
    the cockpit is not importable or holds no session."""
    try:
        from steward_cockpit import steward_engine as _eng
        sid = _eng._read_state_entry(str(effort_dir)).get("session_id")
        return str(sid) if sid else None
    except Exception:
        return None


def ingest_receipts(receipts_root=None, parent_session=None, parent_effort=None) -> int:
    """Sweep the receipt files trio seats dropped (one JSON file per physical
    receipt; the sink renames a complete file into place, so a file that does
    not parse is junk and is removed) into rows through the seam: ``source=seat``,
    keyed by the seat's native session (its own engine session when uuid-shaped,
    so it is the ledger doc), attributed by the ids the seat inherited, else by
    the folder it ran in (a worktree outside the project joins at the project
    folder, like a job). A seat that names no spawner is the steward's whose
    effort it ran under: the sweeping steward's own (``parent_session`` /
    ``parent_effort``), else the session the cockpit state holds for that
    effort. A seat whose native session is already a job's engine session or a
    recorded child is skipped (counted once: the job or the child wins). A
    re-prompted seat (a second call on the same session) is its own row. A
    consumed file is removed. Returns the ledger rows written. Never raises."""
    root = Path(receipts_root) if receipts_root is not None else receipts_dir()
    try:
        files = sorted(root.glob("*.json")) if root.is_dir() else []
    except OSError:
        return 0
    written = 0
    owned = {}
    own = _scope(parent_effort)
    for path in files:
        try:
            r = json.loads(io.open(path, encoding="utf-8", errors="replace").read())
        except (OSError, ValueError):
            try:
                path.unlink()
            except OSError:
                pass
            continue
        if not isinstance(r, dict):
            r = {}
        ids = r.get("env") if isinstance(r.get("env"), dict) else {}
        project_id = ids.get("project_id") or None
        effort_dir = ids.get("effort_dir") or r.get("cwd") or None
        folder_path = None
        if project_id:
            try:
                import rnd_registry as _rr
                folder_path = (_rr.get_project(project_id) or {}).get("folder_path") or None
            except Exception:
                folder_path = None
            if not folder_path:
                folder_path = resolve_project(effort_dir)[1]
        elif effort_dir:
            project_id, folder_path = resolve_project(effort_dir)
        native = r.get("native_id") if isinstance(r.get("native_id"), str) and r.get("native_id") else None
        usage = r.get("usage") if isinstance(r.get("usage"), dict) else None
        tokens = _seat_tokens(usage)
        if folder_path and not _under(effort_dir, folder_path):
            effort_dir = r.get("cwd") if _under(r.get("cwd"), folder_path) else folder_path
        key = "seat:%s" % (native or path.stem,)
        if r.get("kind") == "schema_reprompt":
            key += ":reprompt"
        if native and project_id:
            if project_id not in owned:
                owned[project_id] = _owned_sessions(project_id)
            if native in owned[project_id]:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
        cost = _cost_number(r.get("cost_usd"))
        doc = native if _uuid_like(native) and (tokens > 0 or cost is not None) else None   # unknown stays index-only
        stamp = r.get("at") if isinstance(r.get("at"), str) and r.get("at").endswith("Z") else None
        parent = ids.get("session_id") or ids.get("job_id") or None
        if not parent and parent_session and own and _scope(effort_dir) == own:
            parent = parent_session
        if not parent and ids.get("effort_dir"):
            parent = _steward_session_for(ids.get("effort_dir"))
        written += ingest_usage(
            doc, _ul.entry_key(doc or "", line=key), index_key=key,
            source=SOURCE_SEAT, native_id=native or path.stem, tokens=tokens,
            cost_usd=cost, project_id=project_id,
            folder_path=folder_path, effort_dir=effort_dir, cli=r.get("family") or None,
            model=r.get("model_served") or None, attested=r.get("model_attested"),
            duration_ms=_int(r.get("duration_ms")), usage=usage, parent_id=parent,
            recorded_at=stamp)
        try:
            path.unlink()
        except OSError:
            pass
    return written
