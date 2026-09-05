#!/usr/bin/env python3
"""Anchor rollup honesty — the three-state measured/unmeasured/capture-failed
projection + its render helpers (Honest Telemetry W5).

This is the **sibling structure** the W1 closed-world audit prescribes
(``W1-CLOSED-WORLD-AUDIT.md`` §"Preferred implementation path"): it surfaces the
three honesty states and the capture-rate stamp WITHOUT mutating
``effort_history.project_effort_rollup``'s return dict, so the two exact-shape
legacy assertions (``test_cli_v4::test_cli_rollup_shape_and_delegates`` and
``test_effort_rollup::test_zero_when_no_run_metrics``) stay green UNMODIFIED and
the "superseded" count is 0.

Locked contracts this executes (see ``NORTH-STAR-AMENDMENT.md``):

  - **defer-and-badge (LOCKED).** Discovered/imported efforts contribute exactly 0;
    a pre-feature session is badged ``unmeasured (pre-feature)`` — never a guessed
    total. The numeric rollup stays ``effort_history.project_effort_rollup`` (RUN
    provenance only); this module only classifies + counts.
  - **Tripwire severity (LOCKED).** ``capture-failed`` is a first-class enum state,
    rendered with a **red-tinted** badge visually distinct from BOTH the grey
    ``unmeasured`` badge AND ``$0.00`` — never folded into ``unmeasured``. The
    capture-rate stamp counts capture-failed SEPARATELY (and always renders a
    nonzero capture-failed count).
  - **Gemini-segment RULED letter C (LOCKED).** A session with a measured Claude
    segment AND an unmeasured Gemini/agy segment renders ``partial (gemini segment
    unmeasured)`` — NEVER a complete-looking Claude-only number.
  - **No-own-pricing-table (LOCKED).** ``$`` is shown ONLY when the engine itself
    reported a nonzero ``costUSD``; otherwise a session renders ``… (subscription)``.
    Anchor never computes a dollar figure from a pricing table of its own.

The reason strings are ENUM VALUES (from :mod:`usage_capture`), never free text;
this module only maps them to human-readable hover labels for the badge title.

Pure + stdlib only (``html`` for escaping). Reads the registry + effort store
through the existing read accessors; never spawns a PTY, never calls a model,
never touches the network. Never raises into a render path.
"""

import html as _html

import usage_capture as _uc
import session_registry as _reg

# ── The DISPLAY-state enum (distinct from the finalize/parse enum) ────────────
#: A session whose Claude usage was captured in full.
STATE_MEASURED = "measured"
#: A mixed session — a measured Claude segment + an unmeasured Gemini/agy segment
#: (RULED Option C). Rendered ``partial (gemini segment unmeasured)``.
STATE_PARTIAL = "partial"
#: An honest environmental gap (sidecar pruned / uncorrelated / pre-feature /
#: gemini-only). Grey badge, hover carries the reason enum.
STATE_UNMEASURED = "unmeasured"
#: A CORRECTNESS failure (sidecar present but unparseable / zero-usage-despite-
#: message-lines). Red-tinted badge, NEVER blended into grey, NEVER $0.
STATE_CAPTURE_FAILED = "capture-failed"

#: The render states in stamp order (measured first).
DISPLAY_STATES = (STATE_MEASURED, STATE_PARTIAL, STATE_UNMEASURED,
                  STATE_CAPTURE_FAILED)

# ── Reason enum → human hover label (the finalize/parse reason is the KEY) ─────
_REASON_LABELS = {
    _uc.REASON_SIDECAR_PRUNED:
        "sidecar pruned — the engine's usage file is no longer on disk",
    _uc.REASON_UNCORRELATED:
        "uncorrelated — no engine session id was captured at launch",
    _uc.REASON_SIDECAR_UNAVAILABLE:
        "sidecar store unavailable in this context",
    _uc.REASON_EMPTY_SIDECAR:
        "no measurable turns in the sidecar",
    _uc.REASON_PRE_FEATURE:
        "pre-feature session — never instrumented (defer-and-badge)",
    _uc.REASON_GEMINI_SEGMENT:
        "engine segment unmeasured (Anchor does not capture Gemini/agy or Codex usage)",
    _uc.REASON_PARSE_ERROR:
        "usage file present but unparseable — capture failed",
    _uc.REASON_ZERO_USAGE:
        "usage file present but reported zero usage — capture failed",
}


def reason_label(reason: str) -> str:
    """Human hover label for a finalize/parse reason ENUM value (never free text).

    Falls back to the raw enum value for any reason not in the table (so a new
    enum is surfaced honestly rather than swallowed). ``""`` for no reason.
    """
    r = str(reason or "")
    if not r:
        return ""
    return _REASON_LABELS.get(r, r)


# ── Segment detection (RULED Option C) ────────────────────────────────────────

def has_gemini_segment(record: dict) -> bool:
    """True if the session touched a Gemini/agy segment (unmeasured under Option C).

    Two honest, durable signals: the session ENDED on the gemini backend
    (``backend == 'gemini'``), OR it carries the ``usage_gemini_segment`` marker
    that :func:`terminal_session.switch_engine` stamps when it switches TO an
    engine whose segment is not UUID-captured (so a claude→gemini→claude
    round-trip that ends back on claude is still honestly flagged). Pure.
    """
    if not isinstance(record, dict):
        return False
    # (2026-09-05) a Codex/ChatGPT segment is unmeasured the same way (no pin).
    if (record.get("backend") or "") in (_reg.BACKEND_GEMINI, _reg.BACKEND_CHATGPT):
        return True
    return bool(record.get("usage_gemini_segment"))


# ── The single classifier (pure) — one source of truth for counts + badges ────

def classify_session_usage(record: dict) -> dict:
    """Classify ONE managed-session registry record → its DISPLAY usage state.

    Returns ``{"state": <STATE_*|"">, "reason": <enum|"">, "gemini_segment": bool}``.
    A session with no finalized ``usage_state`` (still running / not yet ended)
    returns ``state == ""`` — it is NOT part of the capture-rate denominator.
    Pure; never raises.

    The mapping executes the locked contracts:
      - finalize ``capture-failed`` → ``capture-failed`` (carrying its reason);
      - finalize ``measured`` + a gemini segment → ``partial`` (Option C);
      - finalize ``measured`` alone → ``measured``;
      - finalize ``unmeasured`` → ``unmeasured`` (reason enum; a gemini-only
        session with no reason is stamped ``gemini-segment``).
    """
    rec = record if isinstance(record, dict) else {}
    usage_state = str(rec.get("usage_state", "") or "")
    usage_reason = str(rec.get("usage_reason", "") or "")
    gemini_seg = has_gemini_segment(rec)

    if usage_state == _uc.STATE_CAPTURE_FAILED:
        return {"state": STATE_CAPTURE_FAILED,
                "reason": usage_reason or _uc.REASON_PARSE_ERROR,
                "gemini_segment": gemini_seg}

    if usage_state == _uc.STATE_MEASURED:
        if gemini_seg:
            # A complete-looking Claude number would HIDE the gemini spend →
            # render 'partial (gemini segment unmeasured)' (RULED Option C).
            return {"state": STATE_PARTIAL,
                    "reason": _uc.REASON_GEMINI_SEGMENT,
                    "gemini_segment": True}
        return {"state": STATE_MEASURED, "reason": "", "gemini_segment": False}

    if usage_state == _uc.STATE_UNMEASURED:
        reason = usage_reason
        if not reason and gemini_seg:
            reason = _uc.REASON_GEMINI_SEGMENT
        return {"state": STATE_UNMEASURED, "reason": reason,
                "gemini_segment": gemini_seg}

    # No finalized state yet (running / pre-end): not in the denominator.
    return {"state": "", "reason": "", "gemini_segment": gemini_seg}


# ── The capture-rate projection (counts + reasons over finalized sessions) ─────

def _session_when(record: dict) -> float:
    """A session's finalize/launch time for windowing: ``cost_final_at`` else
    ``created_at`` (mirrors ``effort_history._member_when``). 0.0 when neither
    parses — treated as out-of-window under 30d (< cutoff), like the numeric
    rollup."""
    for key in ("cost_final_at", "created_at"):
        val = (record or {}).get(key)
        if val in (None, ""):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def project_capture_rate(project_id: str, window: str = "lifetime", now=None):
    """The honest capture-rate over a project's FINALIZED managed sessions (W5).

    Sibling to ``effort_history.project_effort_rollup`` (which stays untouched):
    this counts, per project, how many managed sessions are ``measured`` /
    ``partial`` / ``unmeasured`` / ``capture-failed`` so the dashboard can stamp
    'measured N/T sessions (window) · K capture-failed' — with capture-failed
    ALWAYS counted separately, never folded into unmeasured.

    ``window='30d'`` excludes sessions whose finalize/launch time is older than 30
    days relative to ``now`` (injectable float epoch; defaults to the real clock).
    A session with no finalized ``usage_state`` is excluded from the denominator.

    Returns ``{"window", "total", "measured", "partial", "unmeasured",
    "capture_failed", "reasons": {enum: count}, "per_session": [...]}``. Stdlib
    only; never raises (an empty/failed read yields all-zeros).
    """
    counts = {STATE_MEASURED: 0, STATE_PARTIAL: 0,
              STATE_UNMEASURED: 0, STATE_CAPTURE_FAILED: 0}
    reasons = {}
    per_session = []

    cutoff = None
    if window == "30d":
        import time as _time
        ref = float(now) if now is not None else _time.time()
        cutoff = ref - 30 * 24 * 60 * 60.0

    try:
        sessions = _reg.list_sessions(project_id)
    except Exception:
        sessions = []

    for rec in sessions:
        c = classify_session_usage(rec)
        state = c["state"]
        if not state:
            continue  # not finalized → not in the denominator
        if cutoff is not None and _session_when(rec) < cutoff:
            continue
        counts[state] = counts.get(state, 0) + 1
        if c["reason"]:
            reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
        per_session.append({
            "session_id": rec.get("session_id", ""),
            "lane": rec.get("lane", ""),
            "state": state,
            "reason": c["reason"],
        })

    total = sum(counts.values())
    return {
        "window": window,
        "total": total,
        "measured": counts[STATE_MEASURED],
        "partial": counts[STATE_PARTIAL],
        "unmeasured": counts[STATE_UNMEASURED],
        "capture_failed": counts[STATE_CAPTURE_FAILED],
        "reasons": reasons,
        "per_session": per_session,
    }


def capture_rate_line(rate: dict) -> str:
    """The one-line capture-rate stamp, e.g.
    ``measured 14/17 sessions (30d) · 2 partial · 1 capture-failed``.

    ``measured`` is the numerator (fully-measured sessions only — a ``partial``
    session is NOT counted as measured, per Option C). ``partial`` and
    ``capture-failed`` are appended ONLY when nonzero, and capture-failed is
    ALWAYS shown when nonzero (never folded into unmeasured). Pure text.
    """
    r = rate or {}
    total = int(r.get("total", 0) or 0)
    measured = int(r.get("measured", 0) or 0)
    partial = int(r.get("partial", 0) or 0)
    capfail = int(r.get("capture_failed", 0) or 0)
    window = str(r.get("window", "lifetime") or "lifetime")
    if total <= 0:
        return "no measured sessions yet (%s)" % (window,)
    line = "measured %d/%d session%s (%s)" % (
        measured, total, "" if total == 1 else "s", window)
    if partial:
        line += " · %d partial" % (partial,)
    if capfail:
        line += " · %d capture-failed" % (capfail,)
    return line


# ── Pure render helpers (inline-styled → no external CSS dependency) ───────────
#
# Inline styles keep the three-state visual model self-contained and robust: the
# grey ``unmeasured`` badge and the red-tinted ``capture-failed`` badge are
# structurally distinct here, not dependent on a stylesheet class landing.

#: (background, border, text) per display state. capture-failed is RED-tinted and
#: unmeasured is GREY — the two are visually distinct by construction.
_BADGE_STYLE = {
    STATE_MEASURED: ("rgba(34,197,94,.12)", "rgba(34,197,94,.45)", "#16a34a"),
    STATE_PARTIAL: ("rgba(234,179,8,.12)", "rgba(234,179,8,.5)", "#b8860b"),
    STATE_UNMEASURED: ("rgba(140,140,150,.14)", "rgba(140,140,150,.45)",
                       "#6b7280"),
    STATE_CAPTURE_FAILED: ("rgba(248,81,73,.14)", "rgba(248,81,73,.55)",
                           "#dc2626"),
}

_BADGE_LABEL = {
    STATE_MEASURED: "measured",
    STATE_PARTIAL: "partial",
    STATE_UNMEASURED: "unmeasured",
    STATE_CAPTURE_FAILED: "capture failed",
}


def session_usage_badge(record_or_classification) -> dict:
    """Structured badge for one session's usage state (pure).

    Accepts either a registry record OR a pre-computed ``classify_session_usage``
    dict. Returns ``{"state", "cls", "label", "title", "reason"}``:

      - ``state``  — the DISPLAY state (``measured``/``partial``/``unmeasured``/
        ``capture-failed``/``""`` when not finalized);
      - ``cls``    — a stable CSS class (``ub-meas``/``ub-partial``/``ub-unmeas``/
        ``ub-capfail``) for callers that prefer a stylesheet;
      - ``label``  — the on-badge text (``partial`` for the gemini-segment case);
      - ``title``  — the hover text (the reason label; the gemini-segment call
        reads ``partial (gemini segment unmeasured)``);
      - ``reason`` — the reason ENUM value (never free text).
    """
    src = record_or_classification or {}
    if "state" in src and ("gemini_segment" in src or "reason" in src):
        c = src
    else:
        c = classify_session_usage(src)
    state = c.get("state", "")
    reason = c.get("reason", "") or ""
    cls_map = {STATE_MEASURED: "ub-meas", STATE_PARTIAL: "ub-partial",
               STATE_UNMEASURED: "ub-unmeas", STATE_CAPTURE_FAILED: "ub-capfail"}
    if not state:
        return {"state": "", "cls": "ub-pending", "label": "",
                "title": "", "reason": ""}
    label = _BADGE_LABEL.get(state, state)
    if state == STATE_PARTIAL:
        title = "partial (unmeasured engine segment)"
    else:
        title = reason_label(reason) or label
    return {"state": state, "cls": cls_map.get(state, "ub-unmeas"),
            "label": label, "title": title, "reason": reason}


def badge_html(record_or_classification) -> str:
    """An inline-styled ``<span>`` badge for one session's usage state (pure).

    ``""`` for a not-yet-finalized session (no badge). The capture-failed badge is
    red-tinted; the unmeasured badge is grey — distinct by inline style, never
    blending, so the tripwire severity is visible without a stylesheet. HTML-safe.
    """
    b = session_usage_badge(record_or_classification)
    state = b["state"]
    if not state:
        return ""
    bg, border, color = _BADGE_STYLE.get(state, _BADGE_STYLE[STATE_UNMEASURED])
    style = ("display:inline-block;font-size:10px;font-weight:600;"
             "padding:1px 6px;border-radius:6px;white-space:nowrap;"
             "background:%s;border:1px solid %s;color:%s" % (bg, border, color))
    return ("<span class='usage-badge %s' style=\"%s\" title=\"%s\">%s</span>" % (
        _html.escape(b["cls"], quote=True),
        style,
        _html.escape(b["title"], quote=True),
        _html.escape(b["label"]),
    ))


def capture_rate_html(rate: dict) -> str:
    """The capture-rate stamp as an inline-styled ``<span>`` (pure, HTML-safe).

    Renders :func:`capture_rate_line`; when a nonzero capture-failed count is
    present it is additionally wrapped in a red-tinted inline style so the
    correctness signal reads at a glance on the dashboard. ``""`` never — an
    all-zero project renders the honest 'no measured sessions yet' line.
    """
    line = capture_rate_line(rate)
    capfail = int((rate or {}).get("capture_failed", 0) or 0)
    style = "font-size:11px;color:var(--text-dim,#6b7280);white-space:nowrap"
    if capfail:
        # Tint the whole stamp when capture-failed is present (a real hazard).
        style = ("font-size:11px;color:#dc2626;white-space:nowrap;"
                 "font-weight:600")
    return "<span class='caprate' style=\"%s\">%s</span>" % (
        style, _html.escape(line))
