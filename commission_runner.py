"""Drive a commissioned skill session to a decision point.

WHY THIS EXISTS (root-caused 2026-08-06). Starting a managed session does NOT run a
skill. Every lane seed says, verbatim:

    "Load the Crucible skill now ... greet me EXACTLY once ... Then stop and wait for
     my next message."

That seed is written for a HUMAN to drive from there. So a commissioned session came
up, printed "✓ Crucible loaded — what would you like to do?", and stopped — which is
how a 45-second "planning run" happened that planned nothing. Nobody sent the second
turn.

This module is that second turn, and the watching that follows it. It is the piece
that turns "open a terminal with the skill loaded" into "the steward ran the skill".

WHAT IT DOES NOT DO. It never answers a question the skill asks. When the skill needs
a decision, that is the steward's cue to fetch John — not to guess on his behalf. The
run stops at ASKED and the caller raises it.

Stdlib only. No model calls here: this drives a session and classifies what comes back.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

#: How the run ended.
RUN_ASKED = "asked"          # the skill needs John — raise it, do not answer
RUN_PRODUCED = "produced"    # the skill finished and left something behind
RUN_QUIET = "quiet"          # no output for a long stretch — say so honestly
RUN_DIED = "died"            # the PTY exited
RUN_TIMEOUT = "timeout"      # wall-clock bound hit while still working
#: 0082 (steward-chamber wall-clock accounting): a session that exits BEFORE the
#: greeting ever appears — no output, work turn never sent, seconds of life — is
#: an ENGINE-LAUNCH failure (usage limits, broken CLI), not a session that "died
#: working". The distinction is load-bearing: relaunching a launch failure pays
#: for the identical death again (three cycles, ~80 min, zero product on W11/W12),
#: so the raise must say "fix the engine first", never "the session ended early".
RUN_LAUNCH_FAILURE = "launch_failure"
#: Under this many seconds of life with zero transcript, a dead PTY is a launch
#: failure. Generous vs 0082's observed 858ms–1.2s deaths; far under any real load.
LAUNCH_FAILURE_MAX_SECONDS = 10

#: Default bounds. A real plan run is minutes, not seconds.
DEFAULT_POLL_SECONDS = 10
DEFAULT_MAX_SECONDS = 900
#: Silence this long, with the skill not obviously working, reads as "waiting".
DEFAULT_QUIET_SECONDS = 90
#: Let the composer settle between typing the turn and pressing Enter.
SUBMIT_DELAY_SECONDS = 1.5

#: The greeting the lane seed mandates. Seeing it means the skill LOADED — it is the
#: signal to send the real work turn, and on its own it is NOT progress.
GREETING_RE = re.compile(r"(loaded\s*[—-]\s*what would you like to do|✓\s*\w+\s*loaded)", re.I)

#: A question aimed at the human. Deliberately conservative: a false ASKED just fetches
#: John unnecessarily, while a missed one leaves a session hanging silently.
ASK_PATTERNS = (
    # NOT line-anchored: PTY reads arrive as arbitrary chunks that concatenate with no
    # newline between them, so a question can land mid-"line" in the transcript. A
    # ^-anchored pattern silently missed it and the run read as QUIET — caught by the
    # loop tests, which is exactly the sort of miss that leaves a session hanging.
    re.compile(r"(?:^|[.!?)\]]\s*|\n)\s*(?:\d+[.)]\s*)?"
               r"(?:which|what|do you|would you|should i|shall i)\b[^?\n]{0,200}\?",
               re.I),
    re.compile(r"\b(?:please (?:confirm|choose|decide|specify)|awaiting your|need(?:s)? (?:your )?(?:input|decision|confirmation))\b",
               re.I),
    re.compile(r"^\s*(?:❯|>)\s*\d+\.", re.M),          # a numbered choice list
    re.compile(r"\bAskUserQuestion\b"),
)

#: Evidence the skill actually produced something rather than chatting.
PRODUCED_PATTERNS = (
    re.compile(r"\b(?:wrote|written|created|saved)\b[^\n]{0,80}\.(?:md|json|docx|pptx|xlsx|csv)\b", re.I),
    re.compile(r"\b(?:NORTH-STAR|MASTER-PLAN|IMPLEMENTATION-PLAN|EXECUTION-LOG|DECISION-LOG)\b"),
    re.compile(r"\bhandback\.json\b"),
)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")

#: Signals matched against a WHITESPACE-SQUASHED copy of the transcript.
#:
#: The PTY drops spaces when it wraps, so a real question arrives looking like
#: "revampedBA815(option1,2,or3above—oryourown)?I'llstophereuntil". Every
#: word-boundary pattern silently missed that, and a run that DID ask read as QUIET —
#: caught by reading an actual transcript instead of trusting the outcome field.
SQUASHED_ASK_PATTERNS = (
    re.compile(r"\?i(?:'|’)?llstop", re.I),        # "…? I'll stop here until"
    re.compile(r"\?[^?]{0,40}untilyou", re.I),
    re.compile(r"(?:whichdoyou|whatdoyou|wouldyou|shouldi|shalli)[^?]{0,80}\?", re.I),
    re.compile(r"pleaseconfirm|awaitingyour|needyourdecision|yoursalone", re.I),
    re.compile(r"oryourown\)?\?", re.I),
)


#: Removes the WHOLE mandated greeting, question included.
#:
#: GREETING_RE alone was not enough: its "✓ <skill> loaded" alternative matched only the
#: prefix, leaving "— what would you like to do?" behind, which squashes to
#: "...wouldyou...?" and trips the question patterns. The seed's own hello then read as
#: the skill asking John something.
GREETING_STRIP_RE = re.compile(
    r"✓?\s*\w*\s*loaded\s*[—–-]?\s*what would you like to do\s*\??", re.I)


SQUASHED_GREETING_RE = re.compile(r"[✓●]*\w*loaded[—–-]?whatwouldyouliketodo\??", re.I)


def squash(text: str) -> str:
    """Whitespace-free copy — the PTY's wrapped output loses spaces."""
    return re.sub(r"\s+", "", text or "")


def strip_ansi(text: str) -> str:
    """PTY output carries escape codes; classification must not see them."""
    return _ANSI.sub("", text or "")


def classify(text: str) -> Optional[str]:
    """What does this output say the skill wants? None = still working."""
    if not text:
        return None
    # PRODUCED is checked first: a run that wrote its artifact and then asked
    # "anything else?" has still produced.
    for pat in PRODUCED_PATTERNS:
        if pat.search(text):
            return RUN_PRODUCED
    for pat in ASK_PATTERNS:
        if pat.search(text):
            return RUN_ASKED
    # Drop the mandated greeting BEFORE the squashed pass. Squashed, it reads
    # "...whatwouldyouliketodo?" and trips the question patterns — the seed's own
    # hello would classify as the skill asking John something.
    # Strip the greeting BOTH before and after squashing: the PTY emits it with spaces
    # intact on one line and fully run-together on another, and only the squashed form
    # survives the first pass.
    squashed = SQUASHED_GREETING_RE.sub("", squash(GREETING_STRIP_RE.sub(" ", text)))
    for pat in SQUASHED_ASK_PATTERNS:
        if pat.search(squashed):
            return RUN_ASKED
    return None


def saw_greeting(text: str) -> bool:
    """True once the lane seed's mandated greeting has appeared."""
    return bool(GREETING_RE.search(text or ""))


def run_commissioned_session(
    session_id: str,
    work_turn: str,
    *,
    read_fn: Callable[[str, int], dict],
    write_fn: Callable[[str, str], Any],
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    max_seconds: int = DEFAULT_MAX_SECONDS,
    quiet_seconds: int = DEFAULT_QUIET_SECONDS,
    on_tick: Optional[Callable[[dict], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    watch_only: bool = False,
) -> dict:
    """Drive a loaded skill session with ONE work turn, then watch.

    Returns ``{outcome, transcript, elapsed_s, sent_work_turn, ...}`` where
    ``outcome`` is one of the RUN_* constants. Never answers a question.

    ``watch_only=True`` re-arms the watch WITHOUT sending anything — the mode
    for "John answered the question in the session and handed it back". The
    cursor snaps to the CURRENT end of output first, so the old question can
    never re-classify as a fresh ASKED.
    """
    started = clock()
    cursor = 0
    transcript = ""
    sent = False
    last_new_output = started
    deadline = started + max_seconds

    if watch_only:
        try:
            snap = read_fn(session_id, cursor)
        except Exception as exc:
            return _result(RUN_DIED, transcript, started, clock(), False,
                           detail=f"{type(exc).__name__}: {exc}")
        cursor = snap.get("next", 0)
        if snap.get("status") == "dead":
            return _result(RUN_DIED, transcript, started, clock(), False)
        # From here the loop behaves as if the work turn was already sent —
        # because it was, in the run this one resumes.
        sent = True

    while clock() < deadline:
        try:
            chunk = read_fn(session_id, cursor)
        except Exception as exc:
            return _result(RUN_DIED, transcript, started, clock(), sent,
                           detail=f"{type(exc).__name__}: {exc}")

        text = strip_ansi(chunk.get("text", ""))
        cursor = chunk.get("next", cursor)
        if text:
            transcript += text
            last_new_output = clock()

        if chunk.get("status") == "dead":
            # 0082: dead before the work ever started, with nothing said and
            # only seconds of life = the ENGINE failed at launch. Distinct,
            # loud, and raised as "fix the engine", never "session ended".
            if (not sent and not transcript.strip()
                    and (clock() - started) <= LAUNCH_FAILURE_MAX_SECONDS):
                return _result(RUN_LAUNCH_FAILURE, transcript, started,
                               clock(), sent)
            return _result(RUN_DIED, transcript, started, clock(), sent)

        # THE SECOND TURN. The seed only loads the skill and greets; the work
        # starts when we say what the work is.
        if not sent and (saw_greeting(transcript) or transcript.strip()):
            # TYPE, THEN PRESS ENTER — as two writes.
            #
            # The lane seed gets away with a trailing "\n" because it is written the
            # instant the process starts, before the TUI takes over stdin. A turn sent
            # AFTER the TUI is up is different: "\n" inserts a newline in the composer
            # and the text just sits there unsent. Measured — the work turn appeared in
            # the input box and the session then produced nothing for 130s (classified
            # QUIET, correctly). Enter is a carriage return.
            write_fn(session_id, work_turn.rstrip("\r\n"))
            sleep_fn(SUBMIT_DELAY_SECONDS)
            write_fn(session_id, "\r")
            sent = True
            # Everything before this was load-and-greet noise, not the run.
            transcript = ""
            cursor = chunk.get("next", cursor)
            last_new_output = clock()
            if on_tick:
                on_tick({"event": "work_turn_sent", "elapsed_s": round(clock() - started, 1)})
            sleep_fn(poll_seconds)
            continue

        if sent:
            outcome = classify(transcript)
            if outcome:
                return _result(outcome, transcript, started, clock(), sent)
            if clock() - last_new_output >= quiet_seconds:
                return _result(RUN_QUIET, transcript, started, clock(), sent)

        if on_tick:
            on_tick({
                "event": "tick",
                "elapsed_s": round(clock() - started, 1),
                "chars": len(transcript),
                "sent_work_turn": sent,
            })
        sleep_fn(poll_seconds)

    return _result(RUN_TIMEOUT, transcript, started, clock(), sent)


def _result(outcome, transcript, started, now, sent, **extra) -> dict:
    return {
        "outcome": outcome,
        "transcript": transcript,
        "transcript_chars": len(transcript),
        "elapsed_s": round(now - started, 1),
        "sent_work_turn": sent,
        # An honest run that never got past the greeting is NOT a run.
        "ran": bool(sent and transcript.strip()),
        **extra,
    }
