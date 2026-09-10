"""The steward engine: one persistent Claude Code session with hands.

This is the part the old chamber never had. Instead of a handless one-shot
subprocess per message, we hold ONE long-lived `claude` process in streaming
JSON mode:

    claude -p --input-format stream-json --output-format stream-json ...

- John's messages are written to its stdin as they arrive (queued if a turn
  is mid-flight - never refused, never lost).
- The model streams back; we normalize events for the UI (deltas, tool use,
  turn results with cost).
- The session has real tools and a real permission mode, so the steward can
  read the campaign, write the roadmap, commission skills, and journal -
  exactly like the VS Code sessions that worked.
- A server-owned cadence timer injects the 10-minute status tick while work
  is in flight (mechanism, not a prose promise).
- AskUserQuestion is disallowed at spawn: decisions arrive as prose with the
  question last (the 2026-08-08 lesson, enforced structurally).

Session ids persist to proto-state.json so a server restart resumes the same
conversation instead of starting cold.
"""
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent
STATE_FILE = HERE / "proto-state.json"
# the 10-minute cadence (env-tunable so tests can exercise it in seconds)
TICK_SECONDS = int(os.environ.get("PROTO_TICK_SECONDS", "600"))
TICK_CHECK = max(5, min(30, TICK_SECONDS // 2))
# quiet minutes before the steward sleeps on its own (resume is seamless)
IDLE_SLEEP_SECONDS = int(os.environ.get("PROTO_IDLE_SLEEP_SECONDS", "1800"))
MAX_BUFFER = 4000           # normalized events kept for late joiners

STAND_UP = (
    "Stand up as the steward for this campaign. Invoke the ecgberht skill now, "
    "then follow its READ-BEFORE-PLAN law: open ECGBERHT.md (Face), roadmap.json, "
    "strip.json, .ecgberht/conversation-log.json and the latest journal entries "
    "before saying anything about the campaign. Then greet John with where the "
    "campaign stands in a few plain sentences: goal, active step, what is waiting "
    "on him, and your recommended next move with one line of why. "
    "Do not start any work until he speaks."
)

# Re-asserted periodically (hourly, on the tick) so the deep steward law
# survives compaction on a long session (audit gap #1). Short by design -
# a nudge to re-read the record, not a full re-brief.
REASSERT = (
    "(steward laws still in force - not John) You are Ecgberht, the steward of "
    "this campaign. Before your next action, silently re-read ECGBERHT.md, "
    "roadmap.json and strip.json so your campaign memory is current; keep those "
    "files true, one question at a time, answer John last. Do not narrate this "
    "re-read; just continue. If nothing is pending, reply HOLD."
)

# Sent instead of REASSERT when a parked session RESUMES (John, 2026-08-25:
# "when I start up the session, I need some context"). The deterministic
# pickup lines (_emit_resume_pickup) land instantly from the record; this
# turn adds the model's own two-sentence orientation in plain words.
RESUME_CONTINUITY = (
    "Read the complete durable history and give a brief pickup. Continue agreed "
    "work under explicit, still-current authorization across session or provider "
    "changes; do not require renewed approval solely for the pickup. Honor later "
    "pauses, unresolved decisions, scope limits, and budgets. Ask only for "
    "decisions, permissions, or required inputs that genuinely block the next "
    "action; optional later materials do not block independent authorized work. "
    "Do not replay completed actions; verify uncertain action outcomes before "
    "repeating them. Existing authorization does not expand scope. If no "
    "outstanding authorized task exists, ask John what to do next; do not invent "
    "work or treat the pickup as a new effort."
)

RESUME_BRIEF = (
    "(engine resume - not John) You are Ecgberht, waking from a parked "
    "session. Silently re-read ECGBERHT.md, roadmap.json, strip.json, "
    "DELIVERABLES.md (the register of things worth opening - keep it current "
    "per its standing rule, and answer any 'what have we produced?' from it) "
    "and the complete durable history in .ecgberht/conversation-log.json, then give John a SHORT "
    "pickup - two or three plain sentences: where the campaign stands, the "
    "last thing that happened, and what comes next. If a question is waiting "
    "on him, restate it as the LAST line with enough context that he can "
    "answer from your words alone. "
    + RESUME_CONTINUITY
    + " ATTENTION FLAG (2026-08-25, John saw 'waiting on you' during a live "
    "run): whenever you commission or observe background work - a "
    "researchPrime/Foreman/Gandalf run, a long build - write "
    ".ecgberht/attention.json {\"state\": \"working\", \"reason\": <what is "
    "running, plain words>} the moment it starts, and set it back to "
    "needs_you or quiet the moment it lands; the cockpit's state line and "
    "cadence read ONLY that flag, so an unstamped run looks like idle "
    "waiting to John."
)

CONTRACT = (
    "You are the project steward (Ecgberht) talking with John through a thin "
    "terminal-style page; a rail beside the conversation already shows the goal, "
    "the roadmap steps, and the heartbeat files, repainted every few seconds - "
    "so when you update roadmap.json or strip.json, John sees it move; keep those "
    "files true as you work. Interface contract, earned from the sessions that "
    "worked: (1) conversational replies are a few plain sentences - no headers, "
    "no bullet walls; (2) at most ONE question per turn, asked as the LAST line, "
    "after your recommendation; (3) DECISION SHAPE - when something is John's to "
    "decide, the turn ends in exactly this order, in plain prose: two or three "
    "sentences of CONTEXT (assume he has been away and holds none of it - what is "
    "at stake and why it is live now), then what you RECOMMEND with one line of "
    "why, then the realistic ALTERNATIVES in a phrase each with its trade-off, "
    "then the QUESTION as the LAST line, answerable in one word. Never an option "
    "dialog, never a bare question, never machinery vocabulary. The engine checks "
    "this: a decision turn with no recommendation is sent back once; "
    "(4) the 10-minute status is composed by "
    "the ENGINE into the status pane from the disk map - never post status "
    "tables into the conversation; when a tick arrives, handle the commit and "
    "carry on; "
    "(4b) ATTENTION FLAG - whenever you commission or observe background work "
    "(a researchPrime/Foreman/Gandalf run, a long build), write "
    ".ecgberht/attention.json {\"state\": \"working\", \"reason\": <what is "
    "running, in plain words>} the moment it starts and set it back to "
    "needs_you or quiet the moment it lands. The cockpit's state line and its "
    "cadence read ONLY that flag, so an unstamped run shows John 'waiting on "
    "you' while it works; "
    "(5) John dictates - absorb garbled speech without asking him to repeat, and "
    "never make him restate a standing rule; (6) journal and commit as you go; "
    "(7) an idea John wants parked goes to the Strip's grasscatch list the moment "
    "he says it; (8) when John says go, DRIVE: continue step after step without "
    "asking permission to continue - stop only for a decision that is genuinely "
    "his, an explicit pause, or budget; when you stop for him, end with the "
    "question; (9) when a dictated decision arrives garbled, read it back as ONE "
    "canonical line he can approve with yes; (10) any bullet list you write "
    "starts each bullet with two-four bold lead words, then the detail; "
    "(11) THE EASE METRIC: every John message that is a correction, restatement, "
    "or 'why / are you working' is OVERHEAD - decisions are not; keep the count "
    "and report 'your overhead this session: N' at campaign close or whenever he "
    "asks - the target is zero; (12) commit as you go IS enforced: every cadence "
    "tick that finds the working tree dirty gets a commit with a sensible "
    "message before you continue; "
    "(13) SLICE LOOP (2026-08-28): you own the overall plan. Tag every roadmap "
    "step with part=research|slice|rigor|integrate|harden (the product map is "
    "those tags, not a second file). Pass 1 of a new effort: a substantial draft "
    "covering the whole map; later passes: small slices in this session. You have "
    "NO Shark swarm — that is Crucible, only when commissioned. "
    "Commission Crucible or Foreman only when this session cannot hold the work "
    "AND the step has a gate command (a runner that can fail: tests, render-to-PNG, "
    "a certify script). After EVERY close including research, re-read the North "
    "Star and append a goal_flip event {verdict: reaffirmed|rewritten, goal_from, "
    "goal_to, step_id, receipt}; if rewritten, update the Face. Then recommend "
    "whether to move on; he decides. The cockpit Work product tile is the "
    "living map of the deliverable — same steps as the plan. "
    "(14) PLANS FORWARD (John, 2026-09-04): whenever a plan for going forward "
    "exists or arrives (a researchPrime plan, a Crucible master or "
    "implementation plan, your own PLAN.md), it lives in TWO places at once: a "
    "row in DELIVERABLES.md (so it is a clickable link in the work flow and the "
    "status pane; plan documents named PLAN / MASTER-PLAN / IMPLEMENTATION-PLAN "
    "/ NORTH-STAR appear there on their own) AND a short bullet summary said by "
    "you in the dialogue - three to six bullets, each two-four bold lead words "
    "then the point, ending with the one decision it needs from him if any. "
    "Never a plan he has to go hunting for. "
    "(15) THE DELIVERABLES REGISTER (standing rule, campaign journal 0010): a "
    "step that produces a human-facing artifact is not done until it is a row "
    "in DELIVERABLES.md - a pipe table | What | Where | Date | Step | (Step "
    "optional per row). The Where cell is the open target - an in-effort path "
    "in backticks, or a contained Anchor route (/report/... or /artifact/...) "
    "- and may also carry run: <command> for a runnable deliverable; a row may "
    "carry both. One register, never a second list; the cockpit renders "
    "exactly what you write (the same contract read_deliverables parses). "
    "(16) PLAN DRIFT (John, 2026-09-05): the plan he SEES is roadmap.json. When "
    "he asks to add, remove or reorder elements, or a new North Star / plan "
    "document arrives (yours or a skill's), roadmap.json changes in the SAME "
    "turn - step_create / step_set events plus the projection - and you say in "
    "one line what changed in the plan. A plan document alone is not the plan; "
    "the cockpit appends a PLAN DRIFT line to his turns until the roadmap has "
    "caught up."
)

STAND_UP_NEW = (
    "This is a BRAND-NEW effort: the campaign record here is an empty stub. "
    "Invoke the ecgberht skill now and stand up as the steward. John will "
    "describe what he wants in ordinary conversation — he may not have a "
    "crisp goal yet. When he does: propose a one-sentence goal (labelled as "
    "a proposal he can edit) and a coarse WORK-PRODUCT MAP of the thing he "
    "will actually deliver (paper sections, slide blocks, a software flow), "
    "tagged research|slice|rigor|integrate|harden. Keep the map thin if the "
    "whole effort fits in one sitting. Ask him to correct goal and map. Once "
    "he confirms, write the Face and the tagged roadmap. Then produce a "
    "substantial first draft covering the map unless it fits in one sitting. "
    "Right now, greet him with ONE sentence inviting him to describe the "
    "effort. Do nothing else yet."
)

# (2026-08-25) The status-table demand is GONE from the tick: the engine now
# composes the deterministic two-part status itself (_status_update) and
# routes it to the status pane — the audit's written trigger for dropping the
# model-posted table ("when the deterministic line grows commissioned-run
# rows"). The tick is only the commit nudge now.
TICK = (
    "(engine tick - not John) 10-minute cadence: the status pane is already "
    "painted by the engine - do NOT post a status table. If the working tree "
    "is dirty, commit it now with a sensible message and say so in one line. "
    "If nothing changed and the tree is clean, reply with the single word HOLD."
)


_STATE_LOCK = threading.RLock()


def _reported_cost(value):
    """Only an explicit, finite provider dollar figure is a reported cost."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and value >= 0:
            return float(value)
    return None


def _usage_snapshot(usage):
    """Preserve known subtotals without certifying old, unpriced usage."""
    u = usage if isinstance(usage, dict) else {}
    def count(key):
        value = u.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    reported = _reported_cost(u.get("reported_spend", u.get("spend")))
    turns, tokens = count("turns"), count("tokens")
    secs = _reported_cost(u.get("secs")) or 0.0
    unknown = count("unpriced_turns")
    # Older records accumulated missing provider costs as zero. Neither a
    # positive subtotal nor the currently selected family proves coverage.
    if u.get("cost_complete") is not True and "unpriced_turns" not in u:
        unknown = max(turns, 1 if tokens or secs or reported else 0)
    if u.get("cost_complete") is False or (reported is None and (turns or tokens)):
        unknown = max(unknown, 1)
    reported = reported if reported is not None else 0.0
    return {"spend": round(reported, 4) if not unknown else None,
            "reported_spend": round(reported, 4), "cost_complete": not unknown,
            "unpriced_turns": unknown, "tokens": tokens,
            "secs": secs, "turns": turns}


def result_error_text(ev):
    """The text of an error result event (``is_error`` or an error subtype),
    clipped; "" for a clean result. The model's own words, never a guess."""
    if not isinstance(ev, dict):
        return ""
    sub = str(ev.get("subtype") or "")
    is_err = bool(ev.get("is_error")) or (sub.startswith("error") and sub != "")
    if not is_err:
        return ""
    error = ev.get("error")
    txt = (error.get("message") if isinstance(error, dict) else error)
    if not isinstance(txt, str) or not txt.strip():
        txt = " ".join(str(x) for x in (ev.get("errors") or []) if x)
    if not txt:
        txt = ev.get("result")
    if not isinstance(txt, str) or not txt.strip():
        txt = " ".join(str(x) for x in (ev.get("errors") or []) if x) or sub or "error"
    txt = " ".join(str(txt).split())
    return txt if len(txt) <= 240 else txt[:239].rsplit(" ", 1)[0] + "\u2026"


def _campaign_limit(text):
    try:
        from steward_cockpit import steward_campaign as campaign
        return campaign.classify_model_limit(text)
    except Exception:
        return ""


def _load_state():
    # Missing file -> {} is fine (first run). A PRESENT-but-unreadable file is
    # NOT fine: returning {} there and then saving would wipe every session,
    # so we raise so callers under _update_state abort the write.
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        raise


def _save_state(state):
    # atomic: write a temp then os.replace, so a reader never sees a half file.
    # On Windows os.replace raises WinError 32 if the destination is open in a
    # concurrent reader - retry briefly rather than silently drop the write.
    tmp = None
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_name(
            STATE_FILE.name + ".%s.%s.tmp" %
            (os.getpid(), threading.get_ident()))
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        for attempt in range(6):
            try:
                os.replace(tmp, STATE_FILE)
                return True
            except PermissionError:
                time.sleep(0.05)
        return False
    except Exception:
        return False
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def _read_all_state():
    """Whole state dict under the lock - the ONLY safe way to read the file
    while sessions may be writing it (a bare read can hit a mid-replace gap)."""
    with _STATE_LOCK:
        try:
            return _load_state()
        except Exception:
            return {}


def _update_state(key, patch):
    """Locked read-modify-write of one session's entry. Never clobbers the
    file on a read error (a corrupt state is left intact for inspection)."""
    with _STATE_LOCK:
        try:
            state = _load_state()
        except Exception:
            return False  # present-but-corrupt: preserve it for inspection
        state.setdefault(key, {}).update(patch)
        return _save_state(state)


def _read_state_entry(key):
    with _STATE_LOCK:
        try:
            return dict(_load_state().get(key, {}))
        except Exception:
            return {}


def rename_state_keys(old_dir, new_dir):
    """Migrate every state entry keyed under ``old_dir`` (the steward's own
    entry + its ``||general||`` terminals) to ``new_dir`` — so usage rollups
    and saved sessions follow an effort RENAME (2026-08-25: an effort dir
    named by a pasted token needed renaming without losing its record)."""
    old, new = str(old_dir), str(new_dir)
    with _STATE_LOCK:
        try:
            state = _load_state()
        except Exception:
            return
        changed = False
        for key in list(state.keys()):
            if key == old or key.startswith(old + "||"):
                state[new + key[len(old):]] = state.pop(key)
                changed = True
        if changed:
            _save_state(state)


def _cli_cmd(cli="claude"):
    exe = shutil.which(cli)
    if not exe:
        return None
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    return [exe]


class Engine:
    def __init__(self, campaign_dir, permission_mode="bypassPermissions",
                 fake=False, model=None, steward="Ecgberht", general=False,
                 tid=None):
        self.dir = str(campaign_dir)
        self.permission_mode = permission_mode
        self.fake = fake
        self.model = None  # stale caller model pins do not override dashboard policy
        self.steward = steward
        self.general = general      # workbench terminal: no steward duties
        self.tid = tid              # terminal id (general sessions only)
        _key = self.dir + (f"||general||{tid or 1}" if general else "")
        stored_entry = _read_state_entry(_key)
        import anchor_settings
        prefs = anchor_settings.load_settings()
        self.cli = stored_entry.get("cli") or prefs["default_cli"]
        self.model_selection = stored_entry.get("model_policy")
        self.policy_override = stored_entry.get("policy_override")
        self._bridge_system_prompt = None
        self._last_submitted = ""
        self._turn_had_tools = False
        self.proc = None
        self._stdout_thread = None  # joined by stop() (state writes finish)
        self.events = []            # normalized, seq-stamped
        # a per-boot epoch so a client can tell its cached `since` is stale
        # after a restart / rebuild (else the transcript goes silent forever)
        self.epoch = stored_entry.get("epoch", 0) + 1
        self.seq = 0
        self._human_asked = False   # last human msg ended with "?" (answer-last)
        self._answer_nudged = False
        # decision-shape nudge: ONE per human decision cycle. A plain bool,
        # cleared only by a human message — keying it on the question STRING
        # looped, because the nudge's own re-ask rewords the question.
        self._decision_nudged = False
        self._tick_count = 0        # for the periodic role re-assert
        self.cond = threading.Condition()
        self.busy = False
        # never-lose: restore undelivered words from the durable record so a
        # park/crash cannot drop what he already typed (2026-08-27).
        self.queue = list(stored_entry.get("pending_queue") or [])
        self.session_id = None
        # (2026-09-04, John) "the total spend tokens, time and $ resets every time I
        # reconnect with Anchor" — the counters started at zero on every engine
        # (re)creation and the turn-end write then REPLACED the durable usage with
        # the smaller in-memory total. Seed them from the record so the totals
        # carry the entire history of the effort.
        _u = _usage_snapshot(stored_entry.get("usage"))
        self.spend = _u["reported_spend"]
        self.unpriced_turns = _u["unpriced_turns"]
        self.tokens, self.secs, self.turns = _u["tokens"], _u["secs"], _u["turns"]
        self.last_output = 0.0
        self.last_tick = 0.0
        self.last_status = 0.0      # deterministic status cadence (separate
                                    # from the model-tick clock: it fires
                                    # during commissioned/background work too)
        self.drive = False          # proactive mode: continue until a real gate
        self.auto_count = 0
        self.broken = False         # bad exit / failed delivery -> red light
        self.last_say = 0.0
        self.turn_started = 0.0     # when the current model turn began (0 = idle)
        self.woke_at = 0.0
        self.john_msgs = 0          # ease-metric floor: his message count
        self.open_question = stored_entry.get("open_question", "")
        self.open_question_kind = stored_entry.get("open_question_kind", "")
        if self.open_question and not self.open_question_kind:
            self.open_question_kind = _question_kind(self.open_question)
        self.turn_text = ""         # the current turn's streamed text
        self.in_tick = False        # events of a cadence-tick turn are tagged
        self._ticks_pending = 0     # ticks sent mid-turn: the NEXT n turns are tick turns
        # files the steward touched (Write/Edit). RELOADED from the durable
        # record (John, 2026-08-26: "you've lost a lot of files"): they were
        # persisted all along (files[-40:]) but the engine started every boot
        # with an empty list, so a restart blanked the pane while the record
        # still held them.
        self.files = list(stored_entry.get("files") or [])
        self._lock = threading.Lock()
        self._status_lock = threading.Lock()

    # ---------- events ----------
    def _emit(self, ev):
        ev["ts"] = time.time()
        with self.cond:
            self.seq += 1
            ev["seq"] = self.seq
            self.events.append(ev)
            if len(self.events) > MAX_BUFFER:
                del self.events[: len(self.events) - MAX_BUFFER]
            self.cond.notify_all()

    def events_since(self, since, timeout=25):
        with self.cond:
            if not any(e["seq"] > since for e in self.events):
                self.cond.wait(timeout)
            evs = [e for e in self.events if e["seq"] > since]
            oldest = self.events[0]["seq"] if self.events else 0
            # gap: client asked past what we still hold (ring trimmed) -> it
            # should note a break rather than splice mid-word
            gap = since > 0 and oldest > since + 1
            return evs, oldest, gap

    # ---------- lifecycle ----------
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def light(self, attention=None):
        """green = working · orange = needs an answer · quiet = idle ·
        red = broken or stuck (bad exit, failed delivery, or busy with no
        output for twice the tick window)."""
        att = attention if attention is not None else self._attention()
        now = time.time()
        stuck = (self.alive() and self.busy
                 and now - max(self.last_output, self.last_say,
                               self.woke_at) > max(2 * TICK_SECONDS, 1200))
        if self.broken or stuck:
            return "red"
        if (self.alive() and (self.busy or self.queue)) or att.get("state") == "working":
            return "green"
        if self.open_question or att.get("state") in ("needs_you", "blocked"):
            return "orange"
        return "quiet"

    def state(self):
        import anchor_settings
        selected = anchor_settings.load_settings()
        pending = selected["default_cli"] != self.cli and not (
            self.policy_override and self.policy_override.get("revision") == selected["settings_revision"])
        attention = self._attention()
        return {
            "alive": self.alive(),
            "busy": self.busy,
            "turn_started": self.turn_started if self.busy else 0.0,
            # commissioned/background work in flight (the attention flag,
            # disk-true) — WITHOUT this the header pill said "waiting on
            # you" while a commissioned run worked (John, 2026-08-25)
            "working_bg": attention.get("state") == "working",
            "attention_state": attention.get("state", ""),
            "attention_reason": attention.get("reason", ""),
            "light": self.light(attention),
            "queued": len(self.queue),
            "session_id": self.session_id,
            "spend_usd": round(self.spend, 4) if not self.unpriced_turns else None,
            "reported_spend_usd": round(self.spend, 4),
            "cost_status": ("reported" if not self.unpriced_turns else
                            "partial" if self.spend else "unavailable"),
            "unpriced_turns": self.unpriced_turns,
            "tokens": self.tokens,
            "turns": self.turns,
            "mode": "fake" if self.fake else self.permission_mode,
            "drive": self.drive,
            "auto_count": self.auto_count,
            # the full durable window, not a 12-line peek (2026-08-26)
            "files": self.files[-40:],
            "cli": self.cli,
            "selected_cli": selected["default_cli"],
            "pending_switch": selected["default_cli"] if pending else None,
            "model_policy": self.model_selection,
            "settings_error": selected.get("settings_error"),
            "john_msgs": self.john_msgs,
            "open_question": self.open_question,
            "open_question_kind": self.open_question_kind,
            "epoch": self.epoch,
        }

    def set_drive(self, on):
        self.drive = bool(on)
        if on:
            self.auto_count = 0
            self._emit({"t": "sys", "text": "drive armed - the steward continues without asking; it stops only for a decision that is yours, a pause, or the cap"})
        else:
            self._emit({"t": "sys", "text": "drive paused - the steward waits for you"})

    def skey(self):
        if not self.general:
            return self.dir
        return self.dir + "||general||" + str(self.tid or 1)

    def _history_thread(self):
        return str(self.tid or 1) if self.general else None

    def _record_conversation(self, role, text, *, turn_id=None):
        """The canonical project history survives provider and process changes."""
        if self.fake or os.environ.get("STEWARD_COCKPIT_FAKE"):
            return True
        try:
            from steward_cockpit.conversation_history import append_turn
            append_turn(self.dir, role, text, thread_id=self._history_thread(),
                        turn_id=turn_id or str(uuid.uuid4()))
            return True
        except (OSError, ValueError) as exc:
            self.broken = True
            self._emit({"t": "sys", "text": "Conversation could not be saved; no further work will be submitted: " + str(exc)})
            _update_state(self.skey(), {"history_error": str(exc)})
            return False

    def _recover_legacy_history(self, entry):
        """Recover one parked, explicitly identified Claude conversation.

        The canonical log wins once present. Never discover unrelated native
        sessions or import over a damaged canonical record.
        """
        if (self.fake or os.environ.get("STEWARD_COCKPIT_FAKE")
                or entry.get("cli") != "claude" or not entry.get("session_id")):
            return False
        from steward_cockpit.conversation_history import has_history
        if has_history(self.dir, thread_id=self._history_thread()):
            return False
        if self.alive() or self.busy:
            raise ValueError("legacy conversation recovery requires a parked session")
        from steward_cockpit.legacy_claude_history import import_legacy_claude
        result = import_legacy_claude(
            self.dir, entry["session_id"], thread_id=self._history_thread(),
            excluded_prompts=(STAND_UP, STAND_UP_NEW, RESUME_BRIEF, REASSERT, TICK))
        self._journal_routing(kind="legacy_conversation_recovered", family="claude",
                              source_session=entry["session_id"], turns=result["imported"])
        self._emit({"t": "sys", "text": f"Recovered {result['imported']} original conversation entries; native transcript retained."})
        return True

    def _history_reference(self):
        if self.fake or os.environ.get("STEWARD_COCKPIT_FAKE"):
            return ""
        from steward_cockpit.conversation_history import has_history
        if not has_history(self.dir, thread_id=self._history_thread()):
            return ""
        relative = (f".ecgberht/terminal-history/{self._history_thread()}.json"
                    if self.general else ".ecgberht/conversation-log.json")
        return ("CONVERSATION CONTINUITY: This is an existing conversation, even if the goal/map is still empty. "
                f"Before answering or working, read the complete durable history in {relative}. "
                "Do not substitute a short summary for John's original instructions. His unresolved requirements remain active; "
                "do not ask him to dictate them again. Read the existing project files as needed. "
                "Distinguish requirements from completed actions: do not replay completed actions; verify uncertain action outcomes before repeating them. Explicit, still-current authorization for outstanding agreed work remains valid across session or provider changes, but does not create new approval or expand scope. Honor later pauses, unresolved decisions, scope limits, and budgets. "
                "If the history cannot be read completely, say so before proceeding.\n")

    def _retain_native_session(self, entry):
        """Retain old provider pointers before replacing the active native ID."""
        family, session_id = entry.get("cli"), entry.get("session_id")
        if not family or not session_id:
            return True
        with _STATE_LOCK:
            # A caller can hold an older entry across a handoff. Merge into
            # the current archive; never replace newer pointers with its copy.
            current = _read_state_entry(self.skey())
            records = list(current.get("provider_sessions") or [])
            for record in entry.get("provider_sessions") or []:
                if record not in records:
                    records.append(record)
            if not any(r.get("family") == family and r.get("session_id") == session_id for r in records):
                records.append({"family": family, "session_id": session_id,
                                "model_policy": entry.get("model_policy"), "preserved_at": time.time()})
            return _update_state(self.skey(), {"provider_sessions": records}) is True

    def _desired_policy(self):
        import anchor_settings
        settings = anchor_settings.get_launch_settings()
        override = self.policy_override or {}
        if override.get("revision") == settings["settings_revision"]:
            target = override["family"]
        else:
            self.policy_override = None
            target = settings["default_cli"]
        return settings, target

    def _journal_routing(self, **event):
        entry = _read_state_entry(self.skey())
        events = list(entry.get("routing_events") or [])
        events.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **event})
        if _update_state(self.skey(), {"routing_events": events[-100:]}) is not True:
            raise RuntimeError("Model routing journal could not be persisted; no fallback launched")
        self._emit({"t": "sys", "text": "MODEL ROUTING (journaled): " + event.get("message", event.get("action", "change"))})

    def _select_available_policy(self, settings, target, excluded=()):
        """Bounded prelaunch selection, exclusively among dashboard families."""
        import model_policy
        ladder = list(dict.fromkeys([target] + [settings[k] for k in ("coding_family", "review_family", "default_cli")]))
        failed = []
        for family in ladder:
            if family in excluded:
                continue
            try:
                if family not in ("claude", "chatgpt", "grok"):
                    raise RuntimeError("native cockpit capability contract is not verified")
                if family == "grok" and not (HERE / "grok_turn_bridge.py").is_file():
                    raise RuntimeError("native Grok cockpit adapter is unavailable")
                selection = model_policy.resolve(family, settings=settings)
            except (ValueError, RuntimeError) as exc:
                failed.append(family)
                self._journal_routing(action="unavailable", family=family,
                                      message=family + " preflight unavailable: " + str(exc))
                continue
            if family != target:
                self._journal_routing(action="failover", requested=target, actual_family=family,
                                      model_served=None, cross_model=False,
                                      message=target + " -> " + family + "; selected-provider fallback, cross_model:false")
                self.policy_override = {"family": family, "revision": settings["settings_revision"],
                                        "reason": "visible_failover", "failed_families": list(excluded)}
            return family, selection
        self._journal_routing(action="halt", message="No capable selected cockpit provider remains")
        raise RuntimeError("No capable selected cockpit provider remains; check subscription health")

    def _rollover_locked(self, target, settings, text):
        """Idle-boundary handoff; the next message is never sent to the old seat."""
        import model_policy
        try:
            target, selection = self._select_available_policy(settings, target)
        except (ValueError, RuntimeError) as exc:
            self._emit({"t": "sys", "text": "Pending provider switch could not start: " + str(exc)})
            return False
        if target not in ("claude", "chatgpt", "grok"):
            self._emit({"t": "sys", "text": target + " cockpit transport is not yet verified; message retained"})
            return False
        try:
            handoff = self._handoff_text()
        except (OSError, ValueError) as exc:
            self._emit({"t": "sys", "text": "Provider switch withheld: conversation history is unreadable: " + str(exc)})
            return False
        old, proc = self.cli, self.proc
        self._emit({"t": "sys", "text": f"Dashboard provider change: {old} -> {target}. Starting a new provider session with a history handoff."})
        if (not self._retain_native_session(_read_state_entry(self.skey()))
                or not _update_state(self.skey(), {"pending_switch": target, "pending_handoff": handoff})):
            self._emit({"t": "sys", "text": "Provider switch withheld: handoff could not be saved; original session retained"})
            return False
        self.proc = None  # old reader cannot alter the replacement's state
        if proc is not None and proc.poll() is None:
            self._kill_tree(proc)
        self.cli, self.model_selection, self.session_id = target, selection, None
        seed = ("Provider handoff. Preserve active user requirements; do not replay completed actions:\n"
                + handoff + "\n\nNEXT MESSAGE (answer this once):\n" + text)
        ok, why = self._wake_locked(fresh=True, seed=seed)
        if ok:
            _update_state(self.skey(), {"pending_switch": None, "pending_handoff": None})
        else:
            self._emit({"t": "sys", "text": "Provider handoff failed: " + why})
        return ok

    def wake(self, fresh=False, seed=None):
        # single-flight: hold the lock across the alive-check + Popen so two
        # concurrent requests never spawn two CLI processes
        with self._lock:
            if self.alive():
                return True, "already awake"
            return self._wake_locked(fresh, seed)

    def _wake_locked(self, fresh, seed):
        entry = _read_state_entry(self.skey())
        is_fake = self.fake or bool(os.environ.get("STEWARD_COCKPIT_FAKE"))
        history_reference = ""
        if not is_fake:
            try:
                self._recover_legacy_history(entry)
                history_reference = self._history_reference()
                settings, target = self._desired_policy()
                import model_policy
                previous = entry.get("model_policy") or {}
                if (not fresh and entry.get("session_id") and target == entry.get("cli")
                        and previous.get("family") == target and previous.get("model") and previous.get("effort")):
                    model_policy.validate_policy(previous.get("requested_policy"))
                    model_policy.launch_args(previous)  # validate frozen argv without changing the logical seat
                    selection = dict(previous)
                else:
                    target, selection = self._select_available_policy(settings, target)
            except (OSError, ValueError, RuntimeError) as exc:
                self._emit({"t": "sys", "text": "Model policy unavailable: " + str(exc)})
                return False, str(exc)
            if target != entry.get("cli"):
                if entry.get("session_id") and not history_reference:
                    self._emit({"t": "sys", "text": "Provider change withheld: this older conversation needs its original transcript recovered into project history first. The original session is retained."})
                    return False, "original conversation recovery required before provider change"
                if not self._retain_native_session(entry):
                    return False, "native conversation pointer could not be preserved"
                fresh = True
                if not seed and history_reference:
                    seed = history_reference + RESUME_CONTINUITY
                elif not seed and entry.get("last_text"):
                    seed = "Provider changed. Read the campaign record before continuing. Prior session summary:\n" + entry["last_text"]
            self.cli, self.model_selection = target, selection
        held = list(entry.get("pending_queue") or [])
        if held and not self.queue:
            self.queue = held
        stored = None if fresh else entry.get("session_id")
        # a stored id from a --fake run must never be handed to the real CLI
        if stored and self.fake != bool(str(stored).startswith("fake-")):
            stored = None
        resuming = bool(stored)

        # Anchor stub seam: the healthcheck / tests set STEWARD_COCKPIT_FAKE=1
        # so the cockpit is exercised through THIS module's stream-json fake
        # (the generic ANCHOR_RUNNER_CMD stub speaks a different protocol).
        if is_fake:
            import sys
            cmd = [sys.executable, str(HERE / "fake_claude.py")]
        else:
            base = _cli_cmd("codex" if self.cli == "chatgpt" else self.cli)
            if not base:
                self._emit({"t": "sys", "text": f"{self.cli} CLI not found on PATH"})
                return False, f"{self.cli} CLI not found"
            persona = ("" if self.general else
                       f"Your name in this interface is {self.steward} - John "
                       "picked that persona; answer to it. ")
            if self.cli in ("chatgpt", "grok"):
                import sys
                bridge = "codex_turn_bridge.py" if self.cli == "chatgpt" else "grok_turn_bridge.py"
                cmd = [sys.executable, str(HERE / bridge),
                       "--target", self.dir, "--model", selection["model"],
                       "--effort", selection["effort"], "--permission-mode", self.permission_mode]
                if stored:
                    cmd += ["--resume", stored]
                self._bridge_system_prompt = persona + CONTRACT + "\n" + history_reference
            elif self.cli == "claude":
                cmd = base + [
                "-p", "--verbose",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--permission-mode", self.permission_mode,
                "--disallowedTools", "AskUserQuestion",
                "--append-system-prompt", persona + CONTRACT + "\n" + history_reference,
                "--name", "steward-proto",
                ] + model_policy.launch_args(selection)
                if stored:
                    cmd += ["--resume", stored]
            else:
                return False, self.cli + " cockpit transport is not yet verified; no provider was substituted"
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                cmd, cwd=self.dir,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=flags,
                env=None if is_fake else model_policy.policy_environment(),
            )
        except Exception as e:
            self._emit({"t": "sys", "text": f"could not start the steward: {e}"})
            return False, str(e)
        self.proc = proc
        _update_state(self.skey(), {"cli": self.cli, "model_policy": self.model_selection,
                                   "policy_override": self.policy_override,
                                   "session_id": stored})

        self.broken = False
        self.busy = False
        self.woke_at = time.time()
        # resume validation: if a resumed process dies within a few seconds
        # (bad session id / rejected flags), clear the id and cold-start once
        if resuming:
            time.sleep(0.1)
            if proc.poll() not in (None, 0):
                _update_state(self.skey(), {"session_id": None})
                self._emit({"t": "sys", "text":
                            "stored session could not resume - starting fresh"})
                if not self.general:
                    self._emit_resume_pickup(entry)
                return self._wake_locked(fresh=True, seed=seed)
        # kept on self so stop() can JOIN it: the reader's EOF handler writes
        # the durable record, and an unjoined write can trail past stop() into
        # whatever STATE_FILE points at by then (tests/healthcheck swap it —
        # the 2026-09-05 proto-state residue finding)
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, args=(proc,), daemon=True)
        self._stdout_thread.start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()
        threading.Thread(target=self._ticker, args=(proc,), daemon=True).start()
        # NOTE: the caller (wake) already holds self._lock, so every send here
        # must be _send_locked - calling _send would re-acquire and deadlock
        initial_prompt = None
        if resuming:
            self._emit({"t": "sys", "text": ("terminal" if self.general else "steward")
                        + " awake - resuming the last session"})
            # context on wake (John, 2026-08-25): instant deterministic pickup
            # from the durable record, then the model's own brief orientation
            # (RESUME_BRIEF also re-asserts the role - audit gap #1 - so the
            # deep campaign-memory discipline can't have drifted away).
            if not self.general:
                self._emit_resume_pickup(entry)
                initial_prompt = RESUME_BRIEF
        elif seed:
            initial_prompt = seed
        elif history_reference:
            self._emit({"t": "sys", "text": "awake - restoring the existing conversation and requirements"})
            initial_prompt = history_reference + RESUME_CONTINUITY
        elif self.general:
            self._emit({"t": "sys", "text": "workbench terminal awake"})
            initial_prompt = (
                "This is the project workbench terminal - a general work "
                "session in this folder, NOT the steward (no campaign duties). "
                "John directs; skills are invoked on his word. Confirm "
                "readiness in one short line.")
        else:
            try:
                from steward_cockpit import steward_campaign as campaign
                is_new = not campaign.read_map(self.dir)["goal"].strip()
            except Exception:
                is_new = False
            if is_new:
                self._emit({"t": "sys", "text": "steward awake - new effort; describe what you want"})
                initial_prompt = STAND_UP_NEW
            else:
                self._emit({"t": "sys", "text": "steward awake - standing up (reading the campaign record)"})
                initial_prompt = STAND_UP
        if initial_prompt is not None and not self._send_locked(initial_prompt):
            self.broken = True
            self._emit({"t": "sys", "text":
                        "initial steward prompt was not delivered - session "
                        "closed instead of reporting a false wake"})
            try:
                proc.stdin.close()
            except Exception:
                pass
            self._kill_tree(proc)
            self.proc = None
            self.busy = False
            return False, "initial prompt delivery failed"
        return True, "awake"

    def _emit_resume_pickup(self, entry):
        """Deterministic context on wake — Last / Plan / Goal / Open, before
        any model turn. Zero-model, from the durable record."""
        last = (entry.get("last_text") or "").strip()
        when = (entry.get("last_used") or "").strip()
        if last:
            outcome = last.replace("\n", " ")[-180:]
            if when:
                outcome = when + " — " + outcome
        elif when:
            outcome = "last talked " + when
        else:
            outcome = "no prior reply on record"
        plan = "no active step"
        goal_line = "no goal on record"
        try:
            from steward_cockpit import steward_campaign as campaign
            m = campaign.read_map(self.dir)
            active = next((s for s in m["steps"] if s["status"] == "active"),
                          None)
            if active:
                tag = (active.get("part") or "").strip()
                name = active["name"]
                plan = "step %d/%d · %s" % (
                    min(m["steps_done"] + 1, m["steps_total"]),
                    m["steps_total"], (tag + ": " + name) if tag else name)
            brief = (m.get("goal_brief") or "").strip()
            if brief:
                goal_line = brief
                if m.get("goal_reread") is False:
                    goal_line += " — not re-read since last close"
        except Exception:
            pass
        q = (self.open_question or "").strip()
        open_line = ("waiting on you: " + q) if q else "nothing waiting on you"
        self._emit({"t": "sys", "text": "Last time: " + outcome})
        self._emit({"t": "sys", "text": "Plan: " + plan})
        self._emit({"t": "sys", "text": "Goal: " + goal_line})
        self._emit({"t": "sys", "text": "Open: " + open_line})

    def stop(self):
        # commit-as-you-go covers an explicit Sleep / shutdown too (finding #4
        # gap): a steward's dirty tree is committed before it parks
        if not self.general and self.alive():
            self._commit_if_dirty("steward checkpoint on sleep")
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=10)
            except Exception:
                self._kill_tree(proc)
        # the reader thread's EOF handler persists state (_hold_queue, the
        # turn-result usage): finish it BEFORE returning, so no state write
        # trails a stop into a since-swapped STATE_FILE
        t = getattr(self, "_stdout_thread", None)
        if t is not None and t is not threading.current_thread():
            t.join(timeout=5)
        # clear busy AND hand back the queue under one lock, so a straggling
        # turn-boundary can't re-set busy=True after we cleared it
        with self._lock:
            self.busy = False
            self._hold_queue("session closed")
        self._emit({"t": "sys", "text": "steward asleep"})

    def _persist_queue(self):
        """Caller holds self._lock. True only when words are durable."""
        return _update_state(
            self.skey(), {"pending_queue": list(self.queue)}) is True

    def _hold_queue(self, reason):
        """Session ending: persist undelivered words. Never drop them.
        Caller holds self._lock."""
        persisted = self._persist_queue()
        n = len(self.queue)
        if n and not persisted:
            self.broken = True
            self._emit({"t": "sys", "text":
                        "queue persistence failed - held words remain in "
                        "memory, but disk durability is not confirmed"})
        if n:
            self._emit({"t": "sys", "text":
                        "held %d queued message(s) (%s) — will deliver on wake"
                        % (n, reason)})
        return persisted

    def _kill_tree(self, proc):
        if proc.poll() is not None:
            return  # never target a PID after our owned process has exited
        # cmd /c wraps the real CLI on Windows; kill the whole tree, not the shim
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ---------- engine switch (workbench terminals) ----------
    def _handoff_text(self):
        """Full record reference; never replace user requirements with a tail."""
        reference = self._history_reference()
        if reference:
            return reference
        blocks, cur = [], ""
        for ev in self.events:
            if ev["t"] == "delta":
                cur += ev.get("text", "")
            elif ev["t"] == "john":
                if cur.strip():
                    blocks.append("ASSISTANT: " + cur.strip())
                cur = ""
                blocks.append("JOHN: " + ev.get("text", ""))
        if cur.strip():
            blocks.append("ASSISTANT: " + cur.strip())
        text = "\n\n".join(blocks)
        if self.files:
            text += "\n\nFILES TOUCHED: " + ", ".join(self.files[-10:])
        return text.strip()

    def switch_cli(self, target):
        target = str(target or "").strip().lower()
        if target not in ("claude", "grok", "gemini", "chatgpt"):
            return {"ok": False, "error": "unknown engine"}
        if target == self.cli and self.alive():
            return {"ok": True, "cli": self.cli}
        if self.busy or self.queue:
            # switching mid-turn would kill the in-flight turn and strand the
            # queue - refuse rather than lose work
            return {"ok": False, "cli": self.cli,
                    "error": "finish or pause the current turn before switching engine"}
        if not (self.fake or os.environ.get("STEWARD_COCKPIT_FAKE")):
            try:
                import anchor_settings, model_policy
                settings = anchor_settings.get_launch_settings()
                if target not in {settings[key] for key in ("default_cli", "coding_family", "review_family")}:
                    return {"ok": False, "error": "provider is not selected on the dashboard"}
                if target not in ("claude", "chatgpt", "grok"):
                    return {"ok": False, "error": target + " cockpit transport is not yet verified"}
                model_policy.resolve(target, settings=settings)
                self.policy_override = {"family": target, "revision": settings["settings_revision"], "reason": "explicit_session_choice"}
            except (ValueError, RuntimeError) as exc:
                return {"ok": False, "error": str(exc)}
        try:
            handoff = self._handoff_text()
        except (OSError, ValueError) as exc:
            return {"ok": False, "cli": self.cli, "error": "conversation history unreadable: " + str(exc)}
        entry = _read_state_entry(self.skey())
        if (not (self.fake or os.environ.get("STEWARD_COCKPIT_FAKE"))
                and entry.get("session_id") and not self._history_reference()):
            return {"ok": False, "cli": self.cli,
                    "error": "original conversation recovery required before provider change; original session retained"}
        old = self.cli
        if not self._retain_native_session(_read_state_entry(self.skey())):
            return {"ok": False, "cli": self.cli, "error": "native session history could not be preserved"}
        if self.alive():
            self._emit({"t": "sys",
                        "text": f"switching {old} -> {target} - restoring the saved project conversation"})
            self.stop()
        seed = None
        if handoff:
            seed = (f"Engine switch: you are taking over this workbench terminal "
                    f"from a {old} session. The handoff transcript follows - read "
                    "it, confirm you have the context in ONE line, then continue "
                    f"where it left off.\n\n{handoff}")
        self.cli = target
        ok, why = self.wake(fresh=True, seed=seed)
        _update_state(self.skey(), {"cli": self.cli})
        return {"ok": ok, "cli": self.cli, "why": why}

    # ---------- talking ----------
    def say(self, text, human=True):
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty"}
        if not self.alive():
            ok, why = self.wake()
            if not ok:
                return {"ok": False, "error": why}

        # One ingress transaction: update the human/control state, append the
        # visible event, and either queue or write stdin under the same lock as
        # result-boundary arbitration. A displayed human turn therefore can
        # never be followed by an automatic nudge/drive write before it lands.
        with self._lock:
            control = ""
            if human:
                if not self._record_conversation("john", text):
                    return {"ok": False, "error": "your message was not accepted because durable conversation storage failed"}
                # Only bare UI commands are controls. "go with option B" and
                # "hold on" are substantive words, not drive switches.
                low = text.lower().rstrip(".!").strip()
                if low == "go":
                    self.drive = True
                    self.auto_count = 0
                    control = "go"
                elif low in ("pause", "stop", "hold"):
                    self.drive = False
                    control = "pause"
                self.last_say = time.time()
                self.john_msgs += 1
                self._human_asked = text.rstrip().endswith("?")
                self._answer_nudged = False
                self._decision_nudged = False

                if self.open_question:
                    kind = (self.open_question_kind
                            or _question_kind(self.open_question))
                    if control and kind != "drive_offer":
                        # Drive is an interface command, not an answer. Never
                        # put a bare approval-shaped token on model stdin.
                        self._emit({"t": "john", "text": text})
                        self._emit({"t": "sys", "text":
                                    ("drive armed" if control == "go"
                                     else "drive paused")
                                    + " - still waiting on: "
                                    + self.open_question})
                        return {"ok": True, "queued": False,
                                "control_only": True}
                    self.open_question = ""
                    self.open_question_kind = ""
                    _update_state(self.skey(), {
                        "open_question": "",
                        "open_question_kind": "",
                    })

            self._emit({"t": "john" if human else "sys", "text": text})
            # (2026-09-05, John: "the plan does not get updated") while the
            # roadmap is behind the plan documents, his turn carries the drift
            # line on the model's stdin - his displayed words stay his own.
            if self.busy:
                # queued RAW: the drift line is computed when this is delivered
                # (a line computed now can be false by then — journal 0111)
                self.queue.append(text)
                if not self._persist_queue():
                    self.queue.pop()
                    self.broken = True
                    self._emit({"t": "sys", "text":
                                "queue persistence failed - your text was "
                                "not accepted; please retry after storage "
                                "is healthy"})
                    return {"ok": False,
                            "error": "could not durably queue your text"}
                self._emit({"t": "sys", "text": "queued - the steward is mid-turn; it will be delivered next"})
                return {"ok": True, "queued": True}
            ok = self._send_locked(text + (self._plan_drift_suffix() if (human and not self.general) else ""))
        if not ok:
            return {"ok": False, "error": "delivery failed - your text was not sent"}
        return {"ok": True, "queued": False}

    def _plan_drift_suffix(self):
        """The PLAN DRIFT line for this campaign dir, or ''. Never raises."""
        try:
            from steward_cockpit import steward_campaign as campaign
            return campaign.plan_drift_suffix(self.dir)
        except Exception:
            return ""

    def _send_locked(self, text):
        """Caller holds self._lock. Returns True iff the write reached stdin."""
        if not (self.fake or os.environ.get("STEWARD_COCKPIT_FAKE")):
            try:
                settings, target = self._desired_policy()
            except (ValueError, RuntimeError) as exc:
                self._emit({"t": "sys", "text": "Model settings unavailable; message not sent: " + str(exc)})
                return False
            if target != self.cli:
                return self._rollover_locked(target, settings, text)
        proc = self.proc
        msg = {"type": "user",
               "message": {"role": "user",
                           "content": [{"type": "text", "text": text}]}}
        if self._bridge_system_prompt:
            msg["system_prompt"] = self._bridge_system_prompt
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            self._bridge_system_prompt = None
            self._last_submitted = text
            self._turn_had_tools = False
            self.busy = True
            self.turn_started = time.time()
            self.turn_text = ""
            return True
        except Exception as e:
            self.broken = True
            self._emit({"t": "sys", "text": f"delivery failed: {e}"})
            return False

    def _send(self, text):
        with self._lock:
            return self._send_locked(text)

    # ---------- reading ----------
    def _read_stdout(self, proc):
        for line in proc.stdout:
            if proc is not self.proc:
                break   # a newer process owns the engine now - stop feeding it
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            self._handle(ev, proc)
        code = proc.poll()
        if proc is not self.proc:
            return   # superseded: do not touch shared state (broken/busy/etc)
        if code not in (0, None):
            self.broken = True
        why = getattr(self, "_model_limit", "") or ""
        self._emit({"t": "sys", "text": f"steward session ended (exit {code})"
                    + (" \u2014 " + why if why else "")})
        # the subprocess died unexpectedly - hand back any queued message the
        # user was promised, rather than orphaning it (same as stop())
        with self._lock:
            self.busy = False
            self._hold_queue("session ended")
        self._status_update(emit=True)

    def _read_stderr(self, proc):
        tail = []
        for line in proc.stderr:
            tail.append(line.strip())
            if len(tail) > 20:
                tail.pop(0)
        if (proc is self.proc and tail
                and proc.poll() not in (0, None)):
            self._emit({"t": "sys", "text": "engine stderr: " + " | ".join(tail[-3:])})

    def _handle(self, ev, proc):
        if proc is not self.proc:
            return   # event from a superseded process - drop it entirely
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            if proc is not self.proc:
                return
            if not self._retain_native_session(_read_state_entry(self.skey())):
                self._emit({"t": "sys", "text": "Native session history could not be preserved; retaining the prior pointer"})
                self.broken = True
                return
            self.session_id = ev.get("session_id")
            # init.model is configuration, not proof of what actually served.
            _update_state(self.skey(), {"session_id": self.session_id, "cli": self.cli,
                                      "model_policy": self.model_selection})
        elif t == "stream_event":
            inner = ev.get("event", {})
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    self.last_output = time.time()
                    self.turn_text += delta.get("text", "")
                    self._emit({"t": "delta", "text": delta.get("text", ""),
                                "tick": self.in_tick})
        elif t == "assistant":
            # tool activity is liveness too - keep the "stuck" light honest
            # through a long tool-only turn (a Foreman/researchPrime wave)
            self.last_output = time.time()
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    self._turn_had_tools = True
                    inp = block.get("input") or {}
                    fp = inp.get("file_path")
                    if (block.get("name") in ("Write", "Edit", "NotebookEdit")
                            and isinstance(fp, str) and fp not in self.files):
                        self.files.append(fp)
                        _update_state(self.skey(), {"files": self.files[-40:]})
                    self._emit({"t": "tool",
                                "name": block.get("name", "?"),
                                "detail": _tool_detail(block),
                                "tick": self.in_tick})
        elif t == "result":
            if proc is not self.proc:
                return   # re-check: a newer process must own this result
            # (2026-09-04, John) a model session limit is TOLD, never swallowed:
            # an error result is said in the pane with its text, a limit raises
            # the flag so the High Seat says "need you" with the reason.
            err_text = result_error_text(ev)
            if self.model_selection:
                actual = ev.get("model_served") if ev.get("model_attested") is True else None
                if self.cli == "claude" and not err_text:
                    usage_models = ev.get("modelUsage")
                    if isinstance(usage_models, dict) and len(usage_models) == 1:
                        actual = next(iter(usage_models))
                self.model_selection = {**self.model_selection, "model_served": actual,
                                        "model_attested": bool(actual)}
                _update_state(self.skey(), {"model_policy": self.model_selection})
            if err_text:
                limit = _campaign_limit(err_text)
                self._model_limit = ("model session limit: " + err_text) if limit else ""
                self._emit({"t": "sys", "text": ("MODEL LIMIT: " if limit else
                                                 "the steward's turn ended in an error: ")
                            + err_text})
                if limit:
                    try:
                        from steward_cockpit import steward_campaign as campaign
                        campaign.write_attention(
                            self.dir, "needs_you", self._model_limit,
                            failure_code="MODEL_LIMIT")
                    except Exception:
                        pass
            cost = _reported_cost(ev.get("total_cost_usd"))
            usage = ev.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            # Codex cached_input_tokens is already included in input_tokens.
            # Claude's separate cache read/create counts are additive.
            turn_tokens = sum(value for key in ("input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens")
                if isinstance((value := usage.get(key)), int)
                and not isinstance(value, bool) and value >= 0)
            self.tokens += turn_tokens
            duration = (_reported_cost(ev.get("duration_ms")) or 0) / 1000
            self.secs += duration
            if cost is None:
                self.unpriced_turns += 1
            else:
                self.spend += cost
            self.turns += 1
            # pinned open question: scan the WHOLE final text for the last
            # question-bearing sentence (not just a trailing "?"), so a
            # question mid-paragraph still pins. Tick turns never pin.
            txt = self.turn_text.strip()

            # The complete result boundary is one arbitration transaction.
            # Exactly one next writer wins: an already accepted human message,
            # one machine nudge, auto-drive, or idle. Status I/O happens only
            # after this decision, so it cannot open an overtaking window.
            with self._lock:
                if proc is not self.proc:
                    return
                was_tick = self.in_tick
                history_saved = (not txt or was_tick or self._record_conversation(
                    "steward", txt, turn_id=f"{self.cli}:{self.session_id}:{self.epoch}:{self.turns}"))
                pinned_now = False
                if not was_tick:
                    sentences = [s.strip() for s in
                                 re.split(r"(?<=[.!?])\s+", txt)
                                 if s.strip().endswith("?")]
                    if sentences:
                        self.open_question = sentences[-1][-280:]
                        self.open_question_kind = _question_kind(
                            self.open_question)
                        pinned_now = True

                _update_state(self.skey(), {
                    "usage": {"spend": round(self.spend, 4) if not self.unpriced_turns else None,
                              "reported_spend": round(self.spend, 4),
                              "cost_complete": not self.unpriced_turns,
                              "unpriced_turns": self.unpriced_turns,
                              "tokens": self.tokens,
                              "secs": int(self.secs),
                              "turns": self.turns},
                    # The outcome is the conclusion, not the opening of a long
                    # reply. Pickup already applies its own display bound.
                    "last_text": txt[-240:],
                    "last_used": time.strftime("%Y-%m-%d %H:%M"),
                    "cli": self.cli,
                    "open_question": self.open_question,
                    "open_question_kind": self.open_question_kind,
                    "epoch": self.epoch,
                })
                self.busy = False
                self._emit({"t": "turn_end",
                            "cost_usd": round(cost, 4) if cost is not None else None,
                            "cost_status": "reported" if cost is not None else "unavailable",
                            "tokens": turn_tokens,
                            "duration_s": round(duration),
                            "tick": was_tick})
                self.in_tick = self._ticks_pending > 0
                self._ticks_pending = max(0, self._ticks_pending - 1)

                if not history_saved:
                    self._hold_queue("conversation persistence failed; queued messages retained")
                elif err_text:
                    # Error turns never trigger answer nudges or auto-drive on
                    # the exhausted provider. Only a confirmed unsubmitted/
                    # rejected turn can replay the original message.
                    if limit and not (self.fake or os.environ.get("STEWARD_COCKPIT_FAKE")):
                        try:
                            import anchor_settings
                            settings = anchor_settings.get_launch_settings()
                            excluded = set((self.policy_override or {}).get("failed_families") or [])
                            excluded.add(self.cli)
                            target, selection = self._select_available_policy(settings, self.cli, excluded=excluded)
                            if ev.get("replay_safe") is True and not self._turn_had_tools:
                                seed = self._last_submitted
                            else:
                                self._journal_routing(action="replay_blocked", family=self.cli,
                                    message="Interrupted action state is uncertain; original turn will not be replayed")
                                seed = ("The previous provider stopped mid-turn. Do not run tools or repeat prior actions. "
                                        "Briefly explain that you are the available replacement provider, but the interrupted "
                                        "turn needs confirmation before continuing. Preserve all queued user messages.")
                            if self._rollover_locked(target, settings, seed):
                                self._model_limit = ""
                                return
                        except (ValueError, RuntimeError) as exc:
                            self._emit({"t": "sys", "text": "Model failover stopped: " + str(exc)})
                    self._hold_queue("model turn failed; no automatic replay")
                # Human ingress always outranks automatic retries/drive.
                elif self.queue:
                    queued = self.queue[0]
                    # the drift line is computed NOW, at delivery (journal 0111)
                    suffix = "" if self.general else self._plan_drift_suffix()
                    if self._send_locked(queued + suffix):
                        self.queue.pop(0)
                    if not self._persist_queue():
                        self.broken = True
                        self._emit({"t": "sys", "text":
                                    "queue state could not be persisted after "
                                    "delivery - delivery is uncertain across "
                                    "a restart"})
                elif (self._human_asked and not txt and not was_tick
                      and not self._answer_nudged and not self.general):
                    self._answer_nudged = True
                    self._human_asked = False
                    self._send_locked(
                        "(interface - not John) You ended without answering "
                        "John in words. Reply now in one or two plain "
                        "sentences.")
                elif (pinned_now and txt and not was_tick
                      and not self.general and not self._decision_nudged
                      and not _has_recommendation(txt)):
                    self._decision_nudged = True
                    self._emit({"t": "sys", "tick": True,
                                "text": "decision shape: asked without a "
                                        "recommendation - sent back once"})
                    self._send_locked(
                        "(interface - not John) You put a decision to John "
                        "without a recommendation. Re-ask it now in his shape, "
                        "in plain words and nothing else: two or three "
                        "sentences of context (assume he has been away and "
                        "holds none of it), then what you RECOMMEND and one "
                        "line of why, then the realistic alternatives in a "
                        "phrase each with the trade-off, then the question as "
                        "the LAST line, answerable in one word.")
                else:
                    if txt:
                        self._human_asked = False
                    self._maybe_drive_locked(was_tick, txt)

            # Publish the post-arbitration truth (including a just-started
            # queued/nudge/drive turn) without holding the stdin arbiter lock.
            self._status_update(emit=True)

    # ---------- proactive drive ----------
    DRIVE_CAP = 50

    def _maybe_drive(self, was_tick=False):
        """Compatibility wrapper for tests/callers outside turn arbitration."""
        with self._lock:
            return self._maybe_drive_locked(was_tick, self.turn_text.strip())

    def _maybe_drive_locked(self, was_tick=False, completed_text=""):
        """Choose and send one drive continuation while holding ``_lock``.

        Human ingress, queued text, nudges, and drive all share this arbiter;
        drive must never stack onto an already accepted turn.
        """
        if self.busy or self.queue or not self.drive or not self.alive():
            return
        if was_tick:
            return   # a cadence-tick turn is not a step - never counts as drive
        txt = (completed_text or "").strip()
        if self.open_question or txt.endswith("?"):
            # the pin already carries the question - don't double-announce
            return
        try:
            from steward_cockpit import steward_campaign as campaign
            att = campaign.read_map(self.dir)["attention"]["state"]
        except Exception:
            att = "unknown"
        # drive housekeeping lines are status-pane traffic, not conversation
        # (handoff 2026-08-25 #4 — CLI declutter): the tick tag routes them
        if att == "needs_you":
            self._emit({"t": "sys", "tick": True,
                        "text": "drive: campaign flag says needs-you - waiting"})
            return
        if self.auto_count >= self.DRIVE_CAP:
            self.drive = False
            self._emit({"t": "sys", "tick": True,
                        "text": f"drive: cap reached ({self.DRIVE_CAP} continues) - pausing; say go to re-arm"})
            return
        self.auto_count += 1
        self._emit({"t": "sys", "tick": True,
                    "text": f"drive: continuing ({self.auto_count})"})
        self._send_locked(
            "(drive - not John) Continue. Next step per the plan; stop only "
            "for a decision that is genuinely John's, and if you stop, end "
            "with the question.")

    # ---------- cadence ----------
    def _attention(self):
        """Read the current campaign work state once for a state snapshot."""
        if self.general:
            return {}
        try:
            from steward_cockpit import steward_campaign as campaign
            return campaign.read_map(self.dir).get("attention", {})
        except Exception:
            return {"state": "unknown", "reason": "Work status unavailable"}

    def _working_bg(self):
        """True when the campaign flag says commissioned/background work is
        in flight — disk truth, zero-model. The steward's own turn may be
        idle while a commissioned run (Gandalf, Foreman) works; the old
        busy-only cadence showed NOTHING for exactly the long work John
        wants to watch (handoff 2026-08-25 #2a)."""
        return self._attention().get("state") == "working"

    def _status_update(self, emit=True):
        """The 10-minute status OF RECORD — deterministic, two-part,
        zero-model (the audit's 'status treatment A' grown to commissioned
        runs). TOP: what is running now. BOTTOM: where the whole plan
        stands. Persisted to <cdir>/.ecgberht/status-summary.json — the
        UNIVERSAL file both the cockpit's right pane and the main-dashboard
        project tile read — and (emit=True) sent as a 'status' event the
        client routes to the status pane only, never the conversation."""
        if self.general:
            return False
        # Compose, persist, and emit one generation under one lock. A ticker
        # and a result boundary can request status concurrently; neither may
        # overwrite or replay an older truth after the newer one.
        with self._status_lock:
            try:
                from steward_cockpit import steward_campaign as campaign
                status = campaign.compose_status(self.dir, self.state())
            except Exception as exc:
                self._emit({"t": "sys", "tick": True,
                            "text": "status compose failed: "
                                    + type(exc).__name__})
                return False
            # (2026-09-04, John) a commissioned run that STOPPED — a model
            # session limit above all — must reach him, never just stop: flip a
            # flag still saying "working" to needs_you with the run's reason,
            # so the High Seat and the rail say "need you", and say it once here.
            try:
                flipped = campaign.raise_halt_attention(self.dir, status)
                if flipped:
                    self._emit({"t": "sys", "text": "STOPPED: " + flipped["reason"]})
                    status = campaign.compose_status(self.dir, self.state())
            except Exception:
                pass

            persisted = False
            tmp = None
            try:
                f = Path(self.dir) / ".ecgberht" / "status-summary.json"
                f.parent.mkdir(parents=True, exist_ok=True)
                tmp = f.with_name(
                    f.name + ".%s.%s.tmp" %
                    (os.getpid(), threading.get_ident()))
                tmp.write_text(json.dumps(status, indent=2) + "\n",
                               encoding="utf-8")
                os.replace(tmp, f)
                persisted = True
            except Exception as exc:
                self._emit({"t": "sys", "tick": True,
                            "text": "status persistence failed: "
                                    + type(exc).__name__})
            finally:
                if tmp is not None:
                    try:
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass

            # Notification-budget counter (2026-08-25 elegance S-batch, B6
            # bar): count each transition INTO needs_you per local day.
            try:
                cur = str(((status.get("plan") or {}).get("attention")) or "")
                prev = getattr(self, "_last_attention_state", None)
                self._last_attention_state = cur
                if cur == "needs_you" and prev not in (None, "needs_you"):
                    self._delivery_patch(lambda d: d.update(
                        pings={"date": time.strftime("%Y-%m-%d"),
                               "count": (
                                   d.get("pings", {}).get("count", 0) + 1
                                   if d.get("pings", {}).get("date")
                                   == time.strftime("%Y-%m-%d") else 1)}))
            except Exception:
                pass
            if emit:
                self._emit({"t": "status", "status": status})
            return persisted

    # ---------- delivery receipts (2026-08-25 elegance S-batch) ----------
    #: One lock for ALL delivery.json RMWs (review finding #3: concurrent acks +
    #: the ping counter raced an unlocked read-modify-write and lost updates).
    _DELIVERY_LOCK = threading.Lock()

    def _delivery_patch(self, mutate):
        """Atomically read-modify-write <cdir>/.ecgberht/delivery.json —
        locked, with _save_state's WinError-32 retry (a concurrent reader
        holding the file must delay, never drop, the write)."""
        # NOTE 2026-08-26: this said ``StewardEngine._DELIVERY_LOCK``. The class
        # is ``Engine`` — so EVERY call raised NameError, swallowed by the
        # callers' except-blocks: channel_verified never flipped and the ping
        # counter never counted from the moment the lock was introduced. The
        # receipt mechanism was reporting success while writing nothing.
        with Engine._DELIVERY_LOCK:
            f = Path(self.dir) / ".ecgberht" / "delivery.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                d = {}
            mutate(d)
            tmp = f.with_suffix(f".tmp-{os.getpid()}")
            tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
            for _attempt in range(6):
                try:
                    os.replace(tmp, f)
                    return d
                except PermissionError:
                    time.sleep(0.05)
            f.write_text(json.dumps(d, indent=2), encoding="utf-8")
            return d

    def record_status_ack(self, at=""):
        """The wakeup-delivery lesson, mechanized: the pane POSTs an ack AFTER
        it RENDERS a status, so delivery is a receipt, not a hope. The first
        ack ever flips channel_verified — the one-time 'this channel reaches
        John' acknowledgment; every ack updates the render-leg log."""
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            state = {"first": False}
            def _mut(d):
                state["first"] = not d.get("channel_verified")
                d["channel_verified"] = True
                if state["first"]:
                    d["channel_verified_at"] = now
                d["last_render_ack_at"] = now
                d["last_acked_status_at"] = str(at or "")
                d["render_acks"] = int(d.get("render_acks", 0)) + 1
            self._delivery_patch(_mut)
            return {"ok": True, "channel_verified_first_time": state["first"]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _ticker(self, proc):
        while proc is self.proc and proc.poll() is None:
            time.sleep(TICK_CHECK)
            if proc is not self.proc:   # superseded by a newer process
                return
            now = time.time()
            # automatic sleep: quiet (no talk, no work, nothing queued) for
            # IDLE_SLEEP_SECONDS -> park the process; resume is seamless.
            # A commissioned/background run COUNTS AS WORK: the engine stays
            # awake so the 10-minute status keeps flowing while it runs.
            if (not self.busy and not self.queue
                    and now - max(self.last_say, self.last_output,
                                  self.woke_at) > IDLE_SLEEP_SECONDS
                    and not self._working_bg()):
                # commit-on-idle-close is a real mechanism, not a prompt
                self._commit_if_dirty("steward auto-sleep checkpoint")
                self._emit({"t": "sys", "text":
                            f"steward asleep after {IDLE_SLEEP_SECONDS // 60} "
                            "quiet minutes - everything saved; your next message wakes it"})
                self.stop()
                return
            # THE DETERMINISTIC STATUS CADENCE (handoff 2026-08-25 #2): fires
            # during the steward's OWN busy turn AND during commissioned/
            # background work — the case the old busy-only trigger missed.
            # Zero-model; pane + universal file, never the conversation.
            if (not self.general and now - self.last_status > TICK_SECONDS
                    and (self.busy or self.queue or self._working_bg())):
                self.last_status = now
                self._status_update()
            # the model-facing cadence nudge (commit + HOLD; the status-table
            # demand is gone — the engine composes the status now)
            if (self.busy
                    and now - self.last_output > TICK_SECONDS
                    and now - self.last_tick > TICK_SECONDS):
                # mid-turn: the CLI queues it; it lands at the turn boundary
                self.last_tick = now
                self._tick_count += 1
                try:
                    with self._lock:
                        self._ticks_pending += 1
                        self._send_locked(TICK)
                        # periodic role re-assert (audit gap #1): roughly hourly,
                        # remind the steward of its laws so a long compacting
                        # session can't quietly drift out of role
                        if not self.general and self._tick_count % 6 == 0:
                            self._ticks_pending += 1
                            self._send_locked(REASSERT)
                except Exception:
                    pass
            # commit-as-you-go IS a mechanism now: a dirty tree gets committed
            # on the cadence, independent of whether the model remembers
            if now - self.last_tick < 2:
                self._commit_if_dirty("steward cadence checkpoint")

    def _commit_if_dirty(self, message):
        if self.fake:
            return
        try:
            dirty = subprocess.run(
                ["git", "status", "--porcelain"], cwd=self.dir,
                capture_output=True, text=True, timeout=15)
            if dirty.returncode != 0 or not dirty.stdout.strip():
                return
            subprocess.run(["git", "add", "-A"], cwd=self.dir,
                           capture_output=True, timeout=30)
            subprocess.run(["git", "commit", "-m", message], cwd=self.dir,
                           capture_output=True, timeout=30)
            # cadence housekeeping → the status pane, not the conversation
            self._emit({"t": "sys", "tick": True,
                        "text": "committed work-in-progress (cadence)"})
        except Exception:
            pass


#: Phrases that mark a real recommendation, checked over the TAIL of the turn
#: only (where the decision lives). Deliberately NARROW after the 2026-08-26
#: review: a false POSITIVE silently disables the check, which is the
#: expensive direction. Dropped from an earlier draft: bare "recommended"
#: (matches "as recommended by the plan") and "my call" (matches the exact
#: opposite sentence, "that's not my call - it's yours").
_RECOMMEND_RE = re.compile(
    r"\b(i\s*(?:'|\u2019)?\s*(?:d|would)?\s*(?:recommend|suggest|propose)"
    r"|i\s*(?:'|\u2019)?\s*d?\s*lean\s+toward"
    r"|i\s*(?:'|\u2019)?\s*d?\s*go\s+with"
    r"|i\s+think\s+we\s+should|my\s+recommendation|my\s+advice\s+is"
    r"|recommendation\s*[:\u2014-]|the\s+right\s+move\s+is)", re.I)

#: How much of the turn tail counts as "where the decision is stated".
_RECOMMEND_TAIL = 1200


_DRIVE_OFFER_RE = re.compile(
    r"^(?:shall i drive|shall i keep going|should i keep going|"
    r"do you want me to (?:drive|keep going)|"
    r"would you like me to (?:drive|keep going))\?$", re.I)


def _question_kind(question) -> str:
    """Classify the pinned question without substring false positives.

    A drive offer is deliberately a tiny exact grammar. Substantive questions
    that merely contain words such as "continue" always remain decisions.
    """
    normalized = re.sub(r"\s+", " ", (question or "").strip())
    return "drive_offer" if _DRIVE_OFFER_RE.fullmatch(normalized) else "decision"


def _has_recommendation(text) -> bool:
    """True when a decision turn actually carried a recommendation.

    Only the TAIL is searched: a recommendation recorded in the middle of a
    long working narrative is not a recommendation ABOUT the question being
    asked at the end.
    """
    return bool(_RECOMMEND_RE.search((text or "")[-_RECOMMEND_TAIL:]))


def _tool_detail(block):
    inp = block.get("input") or {}
    name = block.get("name", "")
    for key in ("skill", "command", "description", "file_path", "prompt",
                "pattern", "query"):
        if key in inp and isinstance(inp[key], str):
            text = inp[key].replace("\n", " ")
            return text[:90] + ("..." if len(text) > 90 else "")
    return ""
