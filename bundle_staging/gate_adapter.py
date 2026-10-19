#!/usr/bin/env python3
"""Anchor gate adapter — in-session answers to skill gates (Wave 5).

The keystone gate mechanism (MASTER-PLAN.md D2 + "Gate adapter" bullet +
Spike-0): a skill's ``AskUserQuestion`` tool_use **surfaces in the stream-json
output** even though it auto-dismisses headless. Anchor parses that frame into a
prompt-box record, persists ``state=awaiting-input`` onto the job record so a
reattaching client (incl. over Tailscale) can load the pending question, and
answers it by sending the user's choice as a **single plain text turn** into the
running session's stdin — which continues the session.

Frozen requirements satisfied here:
- Parse a stream-json line/stream → detect an ``AskUserQuestion`` tool_use →
  produce a prompt-box record ``{question, options, tool_use_id}`` (carrying
  enough to render: question text, option labels/descriptions, multiSelect).
- Persist the awaiting-input state onto the job record under
  ``paths.WRITE_LOCK`` (``state`` field + ``pending_prompt``) so a fresh client
  can reattach and answer.
- ``answer(job_or_tool_use_id, choice)`` writes a SINGLE stdin text turn to the
  running session and is **single-consumer**: two concurrent answers for one
  ``tool_use_id`` produce exactly ONE stdin write; the second is a no-op. This is
  enforced with the write-lock + a ``gate_consumed`` marker on the record.

The actual stdin write goes to the job's process stdin (owned by
``job_runner``). For NON-gated lanes ``job_runner.launch`` keeps the Wave-4
contract (``stdin=DEVNULL``); for GATED lanes (plan/build) it now opens a
kept-open ``stdin=PIPE`` and registers that live pipe here via
:func:`register_stdin_sink`, so ``answer()`` writes the continuation turn into
the SAME session. The destination is resolved through a small **stdin-sink
registry**: production registers the live process's ``stdin`` (a writable file
object); tests register a fake sink. Live ``claude`` is NEVER invoked here.

The continuation turn is a stream-json-framed user TEXT turn (``role:user``,
``content:"<choice>"``) — NOT a tool_result. SETUP §4 residual risk: an
AskUserQuestion gate auto-dismisses headless and CANNOT be answered via a
tool_result; the model re-asks in plain text and this plain-text user turn
continues the session. This path is inherently FRAGILE / best-effort.

Durability (2026-07 review, Wave 2): answering a gate must not require the
original process's live stdin pipe. A pending gate is ALSO mirrored into a
durable ``<jobs_dir>/<job_id>.gate.json`` (atomic tmp+replace under
``paths.WRITE_LOCK``), so the question still renders after a restart
(:func:`load_pending_prompt` falls back to the gate file), an answer written
while the job is DEAD is recorded instead of failing (:func:`answer_gate` →
``{ok: True, deferred: True}``), and ``job_runner.relaunch`` delivers a
recorded answer exactly once into the relaunched session's seed prompt.

Stdlib only. No third-party imports.
"""

import json
import threading
import time

import paths as _paths
import job_runner as _jr

# ── Constants ──────────────────────────────────────────────────────────────

#: Job state when a gate question is pending an answer.
STATE_AWAITING_INPUT = "awaiting-input"

#: Tool name that denotes a Claude Code gate (the AskUserQuestion tool).
ASK_TOOL_NAME = "AskUserQuestion"

# ── Stdin-sink registry ─────────────────────────────────────────────────────
# Maps job_id -> a writable sink (the running session's process stdin in
# production, or a fake sink object in tests). A sink only needs ``write`` +
# ``flush``. Kept out of job_runner so the Wave-4 launch contract is unchanged.
_SINKS = {}
_SINKS_LOCK = threading.RLock()


def register_stdin_sink(job_id: str, sink) -> None:
    """Register the writable stdin sink for a job.

    ``sink`` is any object exposing ``write(str)`` and ``flush()`` — in
    production the live subprocess's ``stdin``; in tests a fake sink.
    """
    with _SINKS_LOCK:
        _SINKS[job_id] = sink


def _get_stdin_sink(job_id: str):
    """Resolve the stdin sink for a job, falling back to the live process.

    Prefers an explicitly registered sink; otherwise tries the live job's
    process stdin (only present if the job was launched with a stdin pipe).
    Returns ``None`` if no writable destination is available.
    """
    with _SINKS_LOCK:
        sink = _SINKS.get(job_id)
    if sink is not None:
        return sink
    # Fall back to the live job's process stdin if it exposes one.
    with _jr._LIVE_LOCK:
        live = _jr._LIVE.get(job_id)
    if live is not None:
        stdin = getattr(live.proc, "stdin", None)
        if stdin is not None:
            return stdin
    return None


def _drop_stdin_sink(job_id: str) -> None:
    """Forget a job's sink (test/maintenance helper)."""
    with _SINKS_LOCK:
        _SINKS.pop(job_id, None)


# ── Parsing: stream-json AskUserQuestion → prompt-box record ─────────────────

def _find_ask_user_question(obj):
    found = []
    if isinstance(obj, dict):
        if obj.get("name") == "AskUserQuestion":
            found.append(obj)
        elif isinstance(obj.get("function"), dict) and obj["function"].get("name") == "AskUserQuestion":
            found.append(obj)
        else:
            for v in obj.values():
                found.extend(_find_ask_user_question(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_ask_user_question(item))
    return found


def parse_event(event) -> list:
    """Parse one stream-json event (dict or JSON str) → prompt-box records.

    Returns a list of prompt-box records — one per question in the gate's
    ``input.questions`` array — for any ``AskUserQuestion`` ``tool_use`` block
    found in an assistant message. Non-gate events yield an empty list.

    A prompt-box record has the shape::

        {
          "tool_use_id": "toolu_...",   # the tool_use block id
          "question": "...",            # the question text
          "header": "...",              # short header (optional, may be "")
          "options": [                  # render-ready options
            {"label": "...", "description": "..."}, ...
          ],
          "multiSelect": false,
        }

    Multiple questions in a single gate frame share the one ``tool_use_id`` but
    are disambiguated by ``question_index``.
    """
    if isinstance(event, (str, bytes)):
        text = event.decode("utf-8") if isinstance(event, bytes) else event
        text = text.strip()
        if not text:
            return []
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return []
    if not isinstance(event, dict):
        return []

    records = []
    blocks = _find_ask_user_question(event)
    for block in blocks:
        tool_use_id = block.get("id") or block.get("tool_use_id")
        input_data = block.get("input") or block.get("args") or block.get("arguments")
        if not input_data and isinstance(block.get("function"), dict):
            input_data = block["function"].get("arguments")
        
        if isinstance(input_data, str):
            try:
                input_data = json.loads(input_data)
            except Exception:
                pass
                
        if not isinstance(input_data, dict):
            continue
            
        questions = input_data.get("questions") or []
        for q_index, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            opts = []
            for opt in (q.get("options") or []):
                if isinstance(opt, dict):
                    opts.append({
                        "label": opt.get("label", ""),
                        "description": opt.get("description", ""),
                    })
                else:
                    opts.append({"label": str(opt), "description": ""})
            records.append({
                "tool_use_id": tool_use_id,
                "question_index": q_index,
                "question": q.get("question", ""),
                "header": q.get("header", ""),
                "options": opts,
                "multiSelect": bool(q.get("multiSelect", False)),
            })
    return records


def parse_stream(stream) -> list:
    """Parse an iterable of stream-json lines → all prompt-box records.

    ``stream`` may be a list of lines, a file object, or any iterable of
    newline-delimited JSON strings. Returns the flattened list of prompt-box
    records (usually 0 or 1 for a single gate).
    """
    out = []
    for line in stream:
        out.extend(parse_event(line))
    return out


def parse_stream_file(path) -> list:
    """Parse a stream-json ``.jsonl`` fixture file → prompt-box records."""
    from pathlib import Path
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        return parse_stream(fh)


def session_id_from_stream(stream) -> str:
    """Best-effort: pull the ``session_id`` from an init/system event."""
    for line in stream:
        if isinstance(line, (str, bytes)):
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            text = text.strip()
            if not text:
                continue
            try:
                ev = json.loads(text)
            except json.JSONDecodeError:
                continue
        elif isinstance(line, dict):
            ev = line
        else:
            continue
        if ev.get("session_id"):
            return ev["session_id"]
    return None


# ── Durable gate files (durability 2026-07 Wave 2) ──────────────────────────
# A pending gate is mirrored into ``<jobs_dir>/<job_id>.gate.json`` so that
# (a) the question survives a restart and still renders for an interrupted job,
# (b) an answer for a DEAD job is recorded durably instead of failing, and
# (c) ``job_runner.relaunch`` can deliver a recorded answer exactly once (or
# carry an unanswered question to the relaunched job's id).

def gate_file_path(job_id: str):
    """Durable gate-file path for a job (``<jobs_dir>/<job_id>.gate.json``)."""
    return _jr._jobs_dir_for(job_id) / f"{job_id}.gate.json"


def load_gate_file(job_id: str):
    """Return the durable gate-file dict for a job, or ``None``."""
    p = gate_file_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_gate_file(gate: dict) -> None:
    """Persist a gate file atomically (tmp + replace) under the write lock."""
    with _paths.WRITE_LOCK:
        p = gate_file_path(gate["job_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(gate, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)


def _record_gate_answer(job_id: str, choice, delivered=False) -> dict:
    """Record an answer into the job's durable gate file (created if absent).

    ``delivered=True`` additionally stamps ``delivered_at``: the live stdin
    path already delivered the answer into the running session, so a later
    relaunch must never deliver it again (delivered-once semantics).
    """
    with _paths.WRITE_LOCK:
        gate = load_gate_file(job_id)
        if gate is None:
            # Legacy record marked awaiting before the gate-file era — build
            # the file from the record's own prompt so the answer still lands.
            rec = _jr.load_record(job_id) or {}
            gate = {
                "job_id": job_id,
                "prompt": rec.get("pending_prompt") or rec.get("resolved_prompt"),
                "asked_at": None,
                "answered": False,
            }
        gate["answered"] = True
        gate["answer"] = (list(choice) if isinstance(choice, (list, tuple))
                          else choice)
        gate["answered_at"] = time.time()
        if delivered:
            gate["delivered_at"] = time.time()
            gate["delivered_via"] = "stdin"
        _write_gate_file(gate)
        return gate


def mark_gate_delivered(job_id: str, delivered_to=None):
    """Stamp a job's gate file delivered (relaunch's exactly-once bookkeeping).

    Returns the updated gate dict, or ``None`` when the job has no gate file.
    """
    with _paths.WRITE_LOCK:
        gate = load_gate_file(job_id)
        if gate is None:
            return None
        gate["delivered_at"] = time.time()
        if delivered_to:
            gate["delivered_to"] = delivered_to
        _write_gate_file(gate)
        return gate


def carry_gate_file(old_job_id: str, new_job_id: str):
    """Carry an UNANSWERED gate file onto a relaunched job's id.

    Writes ``<new_job_id>.gate.json`` with the same question and stamps the old
    file ``carried_to`` so the stale copy stops surfacing. Returns the carried
    gate (or ``None`` when the old job had no gate file).
    """
    with _paths.WRITE_LOCK:
        gate = load_gate_file(old_job_id)
        if gate is None:
            return None
        carried = dict(gate)
        carried["job_id"] = new_job_id
        carried["carried_from"] = old_job_id
        carried.pop("carried_to", None)
        _write_gate_file(carried)
        gate["carried_to"] = new_job_id
        _write_gate_file(gate)
        return carried


def append_gate_answer_context(prompt, gate) -> str:
    """Fold an answered-but-undelivered gate answer into a relaunch seed.

    The relaunched session never saw the original AskUserQuestion exchange, so
    the recorded answer rides in as plain context appended to the seed prompt.
    """
    p = gate.get("prompt") or {}
    question = p.get("question", "") if isinstance(p, dict) else str(p)
    ans = gate.get("answer")
    if isinstance(ans, (list, tuple)):
        ans = ", ".join(str(a) for a in ans)
    block = (
        "\n\n[Recovered gate answer] While this job was interrupted, the user "
        "answered its pending question. Do not re-ask it.\n"
        f"Question: {question}\n"
        f"Answer: {ans}"
    )
    return (prompt or "") + block


# ── Persisting awaiting-input onto the job record ────────────────────────────

def mark_awaiting_input(job_id: str, prompt: dict) -> dict:
    """Persist a pending gate prompt onto the job record under the write lock.

    Sets ``state`` -> ``awaiting-input`` and stores ``pending_prompt`` (the
    prompt-box record) plus a cleared ``gate_consumed`` marker so a reattaching
    client can load + answer it. The pre-existing runner ``status`` field is
    left untouched (the runner owns process lifecycle); ``state`` is the gate's
    own dimension. Returns the updated record.
    """
    with _paths.WRITE_LOCK:
        rec = _jr.load_record(job_id) or {"job_id": job_id}
        rec["state"] = STATE_AWAITING_INPUT
        rec["pending_prompt"] = prompt
        rec["gate_consumed"] = False
        _jr._write_record(rec)
        # Durable gate file (Wave 2): mirror the pending question to disk so it
        # survives a restart and can be answered while the job is dead.
        _write_gate_file({
            "job_id": job_id,
            "prompt": prompt,
            "asked_at": time.time(),
            "answered": False,
        })
        return rec


def ingest_stream(job_id: str, stream) -> dict:
    """Parse a stream + persist the first gate found onto the job record.

    Convenience for the launch/tail path: scans the stream for an
    ``AskUserQuestion`` gate; if one is found, persists awaiting-input and
    returns the prompt-box record; otherwise returns ``None``.
    """
    records = parse_stream(stream)
    if not records:
        return None
    prompt = records[0]
    mark_awaiting_input(job_id, prompt)
    return prompt


def load_pending_prompt(job_id: str):
    """Return the pending prompt-box record for a job, or ``None``.

    Used by a fresh/reattaching client (incl. over Tailscale) to load the
    question it must answer. Only returns a prompt while the gate is genuinely
    awaiting input and has not yet been consumed.

    Durability (Wave 2): when the record path yields nothing — post-restart the
    job is ``interrupted`` (GATE-2 hides the record's prompt), or a relaunch
    carried the gate to a fresh record that never held awaiting state — prefer
    the DURABLE gate file, so the dashboard can still render the pending
    question. The fallback only surfaces a gate that is still ANSWERABLE:
    unanswered, undelivered, not carried away, and the job not done/cancelled/
    failed (those sessions are over and will never be relaunched — GATE-2).
    """
    rec = _jr.load_record(job_id)
    if rec is not None:
        if (rec.get("state") == STATE_AWAITING_INPUT
                and not rec.get("gate_consumed")
                and rec.get("status") not in _jr.TERMINAL_STATUSES):
            return rec.get("pending_prompt")
    # Durable gate-file fallback (Wave 2).
    status = (rec or {}).get("status")
    if status in (_jr.STATUS_DONE, _jr.STATUS_CANCELLED, _jr.STATUS_FAILED):
        return None
    gate = load_gate_file(job_id)
    if (gate is not None and not gate.get("answered")
            and not gate.get("delivered_at") and not gate.get("carried_to")):
        return gate.get("prompt")
    return None


def _find_job_id(job_id_or_tool_use_id: str):
    """Resolve either a job_id or a pending tool_use_id to a job_id.

    Lets a client answer by the ``tool_use_id`` it saw in the prompt box,
    matching the AC wording ("two concurrent answer POSTs for one tool_use_id").
    """
    # Direct job_id hit?
    if _jr.load_record(job_id_or_tool_use_id) is not None:
        return job_id_or_tool_use_id
    # Otherwise search for a record whose prompt carries this tool_use_id.
    # GATE-1: an ANSWERABLE match (gate state awaiting-input, not consumed,
    # runner status not terminal) always wins, and a consumed/terminal record
    # with the same tool_use_id must NOT shadow a fresh awaiting gate. On
    # multiple answerable matches, prefer the NEWEST (by started_at, falling back
    # to record mtime) so a fresh gate wins over an older one.
    #
    # If there is NO answerable match, fall back to the newest CONSUMED match
    # (looked up via the retired ``resolved_prompt``) purely so ``answer()`` can
    # report the benign "already-consumed" no-op for that tool_use_id rather than
    # an indistinguishable "unknown". The fallback can never shadow an answerable
    # gate because answerable matches take strict priority.
    best_job_id = None
    best_key = None
    consumed_job_id = None
    consumed_key = None
    for rec in _jr.list_records():
        cand_job_id = rec.get("job_id")
        active_prompt = rec.get("pending_prompt") or {}
        if (active_prompt.get("tool_use_id") == job_id_or_tool_use_id
                and rec.get("state") == STATE_AWAITING_INPUT
                and not rec.get("gate_consumed")
                and rec.get("status") not in _jr.TERMINAL_STATUSES):
            sort_key = _record_recency(rec, cand_job_id)
            if best_key is None or sort_key > best_key:
                best_key = sort_key
                best_job_id = cand_job_id
            continue
        # Track consumed/retired matches as a no-op-reporting fallback only.
        retired = rec.get("resolved_prompt") or active_prompt
        if retired.get("tool_use_id") == job_id_or_tool_use_id:
            sort_key = _record_recency(rec, cand_job_id)
            if consumed_key is None or sort_key > consumed_key:
                consumed_key = sort_key
                consumed_job_id = cand_job_id
    if best_job_id is not None:
        return best_job_id
    return consumed_job_id


def _record_recency(rec: dict, job_id) -> float:
    """Recency key for tie-breaking matches — ``started_at`` else record mtime.

    Larger means newer. Used so a fresh awaiting gate wins over an older one
    that happens to share the same tool_use_id.
    """
    started = rec.get("started_at")
    if isinstance(started, (int, float)):
        return float(started)
    try:
        return _jr._record_path(job_id).stat().st_mtime
    except (OSError, AttributeError, TypeError):
        return 0.0


# ── Answering: single-consumer stdin text turn ───────────────────────────────

def _format_turn(choice) -> str:
    """Render the user's choice as a single stdin text-turn payload.

    The continuation is a plain text turn (D2). We emit a stream-json
    user-message envelope terminated by a newline, which is what a long-lived
    ``--input-format stream-json`` session consumes. The exact envelope is not
    asserted by the gate; what matters is that exactly ONE turn is written.
    """
    if isinstance(choice, (list, tuple)):
        text = ", ".join(str(c) for c in choice)
    else:
        text = str(choice)
    envelope = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return json.dumps(envelope, ensure_ascii=False) + "\n"


class AnswerResult:
    """Outcome of an :func:`answer` call.

    ``written`` is True only for the single consumer that actually wrote the
    stdin turn; concurrent duplicates get ``written=False`` (no-oped).
    """

    __slots__ = ("written", "reason", "job_id")

    def __init__(self, written, reason, job_id=None):
        self.written = written
        self.reason = reason
        self.job_id = job_id

    def __repr__(self):
        return (f"AnswerResult(written={self.written!r}, "
                f"reason={self.reason!r}, job_id={self.job_id!r})")


def answer(job_id_or_tool_use_id: str, choice) -> AnswerResult:
    """Answer a pending gate by writing a SINGLE stdin text turn — once.

    Single-consumer guarantee (AC3): the consumed-marker check-and-set and the
    stdin write both happen **inside** ``paths.WRITE_LOCK``, so under concurrency
    exactly one caller observes ``gate_consumed == False``, performs the write,
    and flips the marker; every other concurrent caller sees the marker already
    set and no-ops. The job's ``state`` is advanced off ``awaiting-input`` so a
    reattaching client sees the gate resolved.

    Returns an :class:`AnswerResult`. ``written=True`` for the one consumer;
    ``written=False`` (with a ``reason``) for no-ops / unknown / not-awaiting.
    """
    with _paths.WRITE_LOCK:
        job_id = _find_job_id(job_id_or_tool_use_id)
        if job_id is None:
            return AnswerResult(False, "unknown", None)
        rec = _jr.load_record(job_id)
        if rec is None:
            return AnswerResult(False, "unknown", job_id)
        # GATE-2: a terminal job's session is gone — its gate is unanswerable
        # even if ``state`` still reads awaiting-input. No-op gracefully.
        if rec.get("status") in _jr.TERMINAL_STATUSES:
            return AnswerResult(False, "terminal", job_id)
        if rec.get("state") != STATE_AWAITING_INPUT:
            return AnswerResult(False, "not-awaiting", job_id)
        if rec.get("gate_consumed"):
            # A concurrent (or prior) answer already consumed this gate.
            return AnswerResult(False, "already-consumed", job_id)

        sink = _get_stdin_sink(job_id)
        if sink is None:
            # No writable session to continue. Do NOT consume the gate so a
            # later reattach (once a sink exists) can still answer.
            return AnswerResult(False, "no-sink", job_id)

        # Perform the single stdin write while still holding the lock, then flip
        # the consumed marker atomically with respect to other answerers.
        payload = _format_turn(choice)
        sink.write(payload)
        try:
            sink.flush()
        except Exception:
            pass

        rec["gate_consumed"] = True
        rec["state"] = "running"  # gate resolved; session continues
        rec["answered_at"] = time.time()
        rec["answer"] = (list(choice) if isinstance(choice, (list, tuple))
                         else choice)
        # GATE-1: retire the pending prompt so its tool_use_id can no longer be
        # matched by _find_job_id or surfaced by load_pending_prompt. Retained as
        # resolved_prompt for history. Done in the SAME write-lock critical
        # section as the consume + write, so single-consumer atomicity holds.
        resolved = rec.pop("pending_prompt", None)
        if resolved is not None:
            rec["resolved_prompt"] = resolved
        _jr._write_record(rec)
        # Durable gate file (Wave 2): mirror the answer and mark it DELIVERED —
        # the live stdin write IS the delivery, so a later relaunch of this job
        # must never deliver the answer a second time.
        _record_gate_answer(job_id, choice, delivered=True)
        return AnswerResult(True, "written", job_id)


def _job_is_live(job_id: str, rec) -> bool:
    """True when the job's process can still receive a stdin turn.

    Live = the record says ``running`` AND the process is genuinely alive
    (either owned/draining in this process, or its PID checks alive). An
    interrupted / dead-but-"running" job is NOT live — its gate answer must be
    recorded durably instead of written into a gone pipe.
    """
    if not rec or rec.get("status") != _jr.STATUS_RUNNING:
        return False
    with _jr._LIVE_LOCK:
        live = _jr._LIVE.get(job_id)
    if live is not None and not live.done.is_set():
        return True
    return _jr._pid_alive(rec.get("pid"))


def answer_gate(job_id: str, choice) -> dict:
    """Answer a gate durably — works whether or not the job is live (Wave 2).

    LIVE job: today's stdin-pipe path (:func:`answer`) is unchanged — the
    single continuation turn is written into the running session — and the
    durable gate file additionally records ``{answered, answer, answered_at}``
    (+ ``delivered_at``: the live write IS the delivery). Returns
    ``{ok, deferred: False, reason, job_id}``.

    NOT-live (interrupted / dead) job: the answer is recorded in the durable
    gate file and ``{ok: True, deferred: True}`` is returned instead of
    failing; ``job_runner.relaunch`` delivers it exactly once into the
    relaunched session's seed prompt. A done/cancelled/failed job refuses
    honestly (that session is over and will never be relaunched), as does a
    job with no pending question at all.
    """
    rec = _jr.load_record(job_id)
    gate = load_gate_file(job_id)
    if rec is None and gate is None:
        return {"ok": False, "deferred": False, "reason": "unknown",
                "job_id": job_id}
    if _job_is_live(job_id, rec):
        res = answer(job_id, choice)
        return {"ok": bool(res.written), "deferred": False,
                "reason": res.reason, "job_id": res.job_id or job_id}
    status = (rec or {}).get("status")
    if status in (_jr.STATUS_DONE, _jr.STATUS_CANCELLED, _jr.STATUS_FAILED):
        return {"ok": False, "deferred": False,
                "reason": f"terminal:{status}", "job_id": job_id}
    if gate is not None and gate.get("delivered_at"):
        return {"ok": False, "deferred": False, "reason": "already-delivered",
                "job_id": job_id}
    if gate is None and not (rec or {}).get("pending_prompt"):
        return {"ok": False, "deferred": False, "reason": "not-awaiting",
                "job_id": job_id}
    _record_gate_answer(job_id, choice)
    return {"ok": True, "deferred": True, "reason": "recorded",
            "job_id": job_id}


# ── Queue-first gate answer (rearch W15 — supervisor seam) ───────────────────
# The supervisor seam answers a gate in two steps so the answer is DURABLY
# QUEUED + ACKed before any stdin write, and delivery is exactly-once + retryable
# across a killed IPC hop (IPC contract "gate-answer" row):
#   1. queue_gate_answer  — record the answer in the durable gate file (the ACK).
#   2. deliver_queued_answer — write the single stdin turn supervisor-side, once.

def queue_gate_answer(job_id: str, choice) -> dict:
    """Durably QUEUE a gate answer WITHOUT touching stdin (the ACK).

    The queue write lands in ``<job_id>.gate.json`` before any delivery, so a
    hop killed after the ACK still has the answer (never lost). Idempotent — a
    second queue for an ALREADY-answered gate KEEPS the first answer and never
    re-stamps it (never doubled). Refuses honestly (``{ok: False, reason}``) for
    an unknown / terminal job or one with no pending question.

    Returns the queued gate dict augmented with ``{ok: True}``.
    """
    with _paths.WRITE_LOCK:
        rec = _jr.load_record(job_id)
        gate = load_gate_file(job_id)
        if rec is None and gate is None:
            return {"ok": False, "reason": "unknown", "job_id": job_id}
        status = (rec or {}).get("status")
        if status in (_jr.STATUS_DONE, _jr.STATUS_CANCELLED, _jr.STATUS_FAILED):
            # That session is over and will never be relaunched — unanswerable.
            return {"ok": False, "reason": f"terminal:{status}",
                    "job_id": job_id}
        if gate is None and not (rec or {}).get("pending_prompt"):
            return {"ok": False, "reason": "not-awaiting", "job_id": job_id}
        if gate is not None and gate.get("answered"):
            # Already queued — keep the first answer (idempotent, never doubled).
            out = dict(gate)
            out["ok"] = True
            out["already_queued"] = True
            return out
        out = dict(_record_gate_answer(job_id, choice, delivered=False))
        out["ok"] = True
        return out


def deliver_queued_answer(job_id: str) -> dict:
    """Deliver a QUEUED gate answer to the session's stdin — exactly once.

    Reads the durably-queued answer and, when the job is live with a writable
    stdin sink, writes the single continuation turn via :func:`answer` (which
    enforces the single-consumer + delivered-once markers). A gate already
    delivered (``delivered_at`` set) is a clean no-op — a retry never doubles
    the write. A queued answer with no live sink stays QUEUED (deferred) for a
    later retry / relaunch. Returns ``{delivered: bool, reason}``.
    """
    with _paths.WRITE_LOCK:
        gate = load_gate_file(job_id)
        if gate is None or not gate.get("answered"):
            return {"delivered": False, "reason": "not-queued"}
        if gate.get("delivered_at"):
            return {"delivered": False, "reason": "already-delivered"}
        choice = gate.get("answer")
    # answer() takes WRITE_LOCK itself (re-entrant); it is the single-consumer
    # write path and stamps the gate file delivered, so delivery is exactly once.
    res = answer(job_id, choice)
    if res.written:
        return {"delivered": True, "reason": "written"}
    return {"delivered": False, "reason": res.reason}
