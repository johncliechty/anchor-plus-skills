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
import os
import re
import shutil
import subprocess
import threading
import time
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
RESUME_BRIEF = (
    "(engine resume - not John) You are Ecgberht, waking from a parked "
    "session. Silently re-read ECGBERHT.md, roadmap.json, strip.json, "
    "DELIVERABLES.md (the register of things worth opening - keep it current "
    "per its standing rule, and answer any 'what have we produced?' from it) "
    "and the tail of .ecgberht/conversation-log.json, then give John a SHORT "
    "pickup - two or three plain sentences: where the campaign stands, the "
    "last thing that happened, and what comes next. If a question is waiting "
    "on him, restate it as the LAST line with enough context that he can "
    "answer from your words alone. READ-BACK GATE (campaign journal 0008): if "
    "his first reply is a bare token (go / yes / ok), read the pending "
    "decision back as ONE canonical line and get his yes against THAT line "
    "before spending anything - a bare token across a session boundary is "
    "never an approval by itself. Do not start any work until he speaks. "
    "ATTENTION FLAG (2026-08-25, John saw 'waiting on you' during a live "
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
    "after your recommendation; (3) decisions come as prose carrying their own "
    "context - never option dialogs; (4) the 10-minute status is composed by "
    "the ENGINE into the status pane from the disk map - never post status "
    "tables into the conversation; when a tick arrives, handle the commit and "
    "carry on; "
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
    "message before you continue."
)

STAND_UP_NEW = (
    "This is a BRAND-NEW effort: the campaign record here is an empty stub. "
    "Invoke the ecgberht skill now and stand up as the steward. John will "
    "describe what he wants in his next message. When he does: first reflect it "
    "back - 'Here is what I think your goal is' - one sentence plus bold-lead "
    "bullets - and ask him to verify; once he verifies, write the Face and "
    "propose the roadmap steps (the map) for his confirmation per the engine's "
    "confirm law; when both are verified, wait for his go. Right now, greet him "
    "with ONE sentence inviting him to describe the effort. Do nothing else yet."
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
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        for attempt in range(6):
            try:
                os.replace(tmp, STATE_FILE)
                return
            except PermissionError:
                time.sleep(0.05)
        # last resort: a direct write is better than losing the update
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
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
            return  # present-but-corrupt: do not overwrite good-but-unparsed data
        state.setdefault(key, {}).update(patch)
        _save_state(state)


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
        self.model = model
        self.steward = steward
        self.general = general      # workbench terminal: no steward duties
        self.tid = tid              # terminal id (general sessions only)
        self.cli = "claude"         # terminal seat: claude | grok | gemini
        _key = self.dir + (f"||general||{tid or 1}" if general else "")
        stored_entry = _read_state_entry(_key)
        if general:
            self.cli = stored_entry.get("cli", "claude")
        self.proc = None
        self.events = []            # normalized, seq-stamped
        # a per-boot epoch so a client can tell its cached `since` is stale
        # after a restart / rebuild (else the transcript goes silent forever)
        self.epoch = stored_entry.get("epoch", 0) + 1
        self.seq = 0
        self._human_asked = False   # last human msg ended with "?" (answer-last)
        self._answer_nudged = False
        self._tick_count = 0        # for the periodic role re-assert
        self.cond = threading.Condition()
        self.busy = False
        self.queue = []             # messages waiting for the turn to end
        self.session_id = None
        self.spend = 0.0
        self.tokens = 0
        self.secs = 0.0
        self.turns = 0
        self.last_output = 0.0
        self.last_tick = 0.0
        self.last_status = 0.0      # deterministic status cadence (separate
                                    # from the model-tick clock: it fires
                                    # during commissioned/background work too)
        self.drive = False          # proactive mode: continue until a real gate
        self.auto_count = 0
        self.broken = False         # bad exit / failed delivery -> red light
        self.last_say = 0.0
        self.woke_at = 0.0
        self.john_msgs = 0          # ease-metric floor: his message count
        self.open_question = stored_entry.get("open_question", "")
        self.turn_text = ""         # the current turn's streamed text
        self.in_tick = False        # events of a cadence-tick turn are tagged
        self._ticks_pending = 0     # ticks sent mid-turn: the NEXT n turns are tick turns
        self.files = []             # files the steward touched (Write/Edit)
        self._lock = threading.Lock()

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

    def light(self):
        """green = actively running · orange = quiet/done/asleep ·
        red = broken or stuck (bad exit, failed delivery, or busy with no
        output for twice the tick window)."""
        now = time.time()
        stuck = (self.alive() and self.busy
                 and now - max(self.last_output, self.last_say,
                               self.woke_at) > max(2 * TICK_SECONDS, 1200))
        if self.broken or stuck:
            return "red"
        if self.alive() and (self.busy or self.queue):
            return "green"
        return "orange"

    def state(self):
        return {
            "alive": self.alive(),
            "busy": self.busy,
            # commissioned/background work in flight (the attention flag,
            # disk-true) — WITHOUT this the header pill said "waiting on
            # you" while a commissioned run worked (John, 2026-08-25)
            "working_bg": self._working_bg(),
            "light": self.light(),
            "queued": len(self.queue),
            "session_id": self.session_id,
            "spend_usd": round(self.spend, 4),
            "turns": self.turns,
            "mode": "fake" if self.fake else self.permission_mode,
            "drive": self.drive,
            "auto_count": self.auto_count,
            "files": self.files[-12:],
            "cli": self.cli,
            "john_msgs": self.john_msgs,
            "open_question": self.open_question,
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

    def wake(self, fresh=False, seed=None):
        # single-flight: hold the lock across the alive-check + Popen so two
        # concurrent requests never spawn two CLI processes
        with self._lock:
            if self.alive():
                return True, "already awake"
            return self._wake_locked(fresh, seed)

    def _wake_locked(self, fresh, seed):
        entry = _read_state_entry(self.skey())
        stored = None if fresh else entry.get("session_id")
        # a stored id from a --fake run must never be handed to the real CLI
        if stored and self.fake != bool(str(stored).startswith("fake-")):
            stored = None
        resuming = bool(stored)

        # Anchor stub seam: the healthcheck / tests set STEWARD_COCKPIT_FAKE=1
        # so the cockpit is exercised through THIS module's stream-json fake
        # (the generic ANCHOR_RUNNER_CMD stub speaks a different protocol).
        if self.fake or os.environ.get("STEWARD_COCKPIT_FAKE"):
            import sys
            cmd = [sys.executable, str(HERE / "fake_claude.py")]
        else:
            base = _cli_cmd(self.cli)
            if not base:
                self._emit({"t": "sys", "text": f"{self.cli} CLI not found on PATH"})
                return False, f"{self.cli} CLI not found"
            persona = ("" if self.general else
                       f"Your name in this interface is {self.steward} - John "
                       "picked that persona; answer to it. ")
            cmd = base + [
                "-p", "--verbose",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--permission-mode", self.permission_mode,
                "--disallowedTools", "AskUserQuestion",
                "--append-system-prompt", persona + CONTRACT,
                "--name", "steward-proto",
            ]
            if self.model:
                cmd += ["--model", self.model]
            if stored:
                cmd += ["--resume", stored]
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            proc = subprocess.Popen(
                cmd, cwd=self.dir,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=flags,
            )
        except Exception as e:
            self._emit({"t": "sys", "text": f"could not start the steward: {e}"})
            return False, str(e)
        self.proc = proc

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
                return self._wake_locked(fresh=True, seed=seed)
        threading.Thread(target=self._read_stdout, args=(proc,), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()
        threading.Thread(target=self._ticker, args=(proc,), daemon=True).start()
        # NOTE: the caller (wake) already holds self._lock, so every send here
        # must be _send_locked - calling _send would re-acquire and deadlock
        if resuming:
            self._emit({"t": "sys", "text": ("terminal" if self.general else "steward")
                        + " awake - resuming the last session"})
            # context on wake (John, 2026-08-25): instant deterministic pickup
            # from the durable record, then the model's own brief orientation
            # (RESUME_BRIEF also re-asserts the role - audit gap #1 - so the
            # deep campaign-memory discipline can't have drifted away).
            if not self.general:
                self._emit_resume_pickup(entry)
                self._send_locked(RESUME_BRIEF)
        elif seed:
            self._send_locked(seed)
        elif self.general:
            self._emit({"t": "sys", "text": "workbench terminal awake"})
            self._send_locked("This is the project workbench terminal - a general "
                              "work session in this folder, NOT the steward (no "
                              "campaign duties). John directs; skills are invoked on "
                              "his word. Confirm readiness in one short line.")
        else:
            try:
                from steward_cockpit import steward_campaign as campaign
                is_new = not campaign.read_map(self.dir)["goal"].strip()
            except Exception:
                is_new = False
            if is_new:
                self._emit({"t": "sys", "text": "steward awake - new effort; describe what you want"})
                self._send_locked(STAND_UP_NEW)
            else:
                self._emit({"t": "sys", "text": "steward awake - standing up (reading the campaign record)"})
                self._send_locked(STAND_UP)
        return True, "awake"

    def _emit_resume_pickup(self, entry):
        """Deterministic context on wake (John, 2026-08-25: 'when I start up
        the session, I need some context') — where we left off, composed from
        the durable record: zero-model, instant, can't drift. The model's own
        pickup (RESUME_BRIEF) streams right behind it."""
        bits = []
        if entry.get("last_used"):
            bits.append("last talked " + str(entry["last_used"]))
        try:
            from steward_cockpit import steward_campaign as campaign
            m = campaign.read_map(self.dir)
            active = next((s for s in m["steps"] if s["status"] == "active"),
                          None)
            if active:
                bits.append("step %d/%d · %s" % (
                    min(m["steps_done"] + 1, m["steps_total"]),
                    m["steps_total"], active["name"]))
            wait = (m["heartbeat"]["human_wait"] or "").split("·")[0].strip()
            if wait:
                bits.append("waiting on you: " + wait)
        except Exception:
            pass
        if bits:
            self._emit({"t": "sys", "text": "picking up - " + " · ".join(bits)})
        last = (entry.get("last_text") or "").strip()
        if last:
            self._emit({"t": "sys", "text": "last reply ended: …" + last[-200:]})
        if self.open_question:
            self._emit({"t": "sys", "text": "⚑ still waiting on your answer: "
                                            + self.open_question})

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
        # clear busy AND hand back the queue under one lock, so a straggling
        # turn-boundary can't re-set busy=True after we cleared it
        with self._lock:
            self.busy = False
            for pending in self.queue:
                self._emit({"t": "sys", "text":
                            "not delivered (session closed) - copy it back in: "
                            + pending[:120]})
            self.queue = []
        self._emit({"t": "sys", "text": "steward asleep"})

    def _kill_tree(self, proc):
        # cmd /c wraps the real CLI on Windows; kill the whole tree, not the shim
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10)
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ---------- engine switch (workbench terminals) ----------
    def _handoff_text(self):
        """Deterministic handoff from the live event buffer - no model call."""
        blocks, cur = [], ""
        for ev in self.events[-600:]:
            if ev["t"] == "delta":
                cur += ev.get("text", "")
            elif ev["t"] == "john":
                if cur.strip():
                    blocks.append("ASSISTANT: " + cur.strip())
                cur = ""
                blocks.append("JOHN: " + ev.get("text", ""))
        if cur.strip():
            blocks.append("ASSISTANT: " + cur.strip())
        text = "\n\n".join(blocks)[-3500:]
        if self.files:
            text += "\n\nFILES TOUCHED: " + ", ".join(self.files[-10:])
        return text.strip()

    def switch_cli(self, target):
        target = str(target or "").strip().lower()
        if target not in ("claude", "grok", "gemini"):
            return {"ok": False, "error": "unknown engine"}
        if target == self.cli and self.alive():
            return {"ok": True, "cli": self.cli}
        if self.busy or self.queue:
            # switching mid-turn would kill the in-flight turn and strand the
            # queue - refuse rather than lose work
            return {"ok": False, "cli": self.cli,
                    "error": "finish or pause the current turn before switching engine"}
        handoff = self._handoff_text()
        old = self.cli
        if handoff:
            try:
                hdir = HERE / "handoffs"
                hdir.mkdir(exist_ok=True)
                fname = f"term-{abs(hash(self.skey())) % 99999}-{old}-to-{target}.md"
                (hdir / fname).write_text(
                    f"# Engine switch handoff - {old} -> {target}\n\n" + handoff,
                    encoding="utf-8")
            except Exception:
                pass
        if self.alive():
            self._emit({"t": "sys",
                        "text": f"switching {old} -> {target} - work handed off, nothing lost"})
            self.stop()
        seed = None
        if handoff:
            seed = (f"Engine switch: you are taking over this workbench terminal "
                    f"from a {old} session. The handoff transcript follows - read "
                    "it, confirm you have the context in ONE line, then continue "
                    f"where it left off.\n\n{handoff}")
        self.cli = target
        ok, why = self.wake(fresh=True, seed=seed)
        if not ok and target != "claude":
            self._emit({"t": "sys", "text":
                        f"{target} could not start with streaming flags on this "
                        "machine - falling back to claude with the same handoff; "
                        f"full {target} terminals ride Anchor's engine-switch at integration"})
            self.cli = "claude"
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
        if human:
            low = text.lower().rstrip(".!")
            if low == "go" or low.startswith("go "):
                self.drive = True
                self.auto_count = 0
            elif low in ("pause", "stop", "hold") or low.startswith("pause "):
                self.drive = False
            self.last_say = time.time()
            self.john_msgs += 1
            # answer-last enforcement (audit gap #3): if John literally asks a
            # question, the steward's turn must end in prose, not tool calls
            self._human_asked = text.rstrip().endswith("?")
            self._answer_nudged = False
            if self.open_question:
                # only a HUMAN message answers/supersedes the pinned question;
                # machine sends (drive, grasscatch, gandalf re-run) must not
                self.open_question = ""
                _update_state(self.skey(), {"open_question": ""})
        self._emit({"t": "john" if human else "sys", "text": text})
        # hold the lock across the busy-check AND the send, so a turn boundary
        # can't slip a drive-continue between the check and the write
        with self._lock:
            if self.busy:
                self.queue.append(text)
                self._emit({"t": "sys", "text": "queued - the steward is mid-turn; it will be delivered next"})
                return {"ok": True, "queued": True}
            ok = self._send_locked(text)
        if not ok:
            return {"ok": False, "error": "delivery failed - your text was not sent"}
        return {"ok": True, "queued": False}

    def _send_locked(self, text):
        """Caller holds self._lock. Returns True iff the write reached stdin."""
        proc = self.proc
        msg = {"type": "user",
               "message": {"role": "user",
                           "content": [{"type": "text", "text": text}]}}
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            self.busy = True
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
        self._emit({"t": "sys", "text": f"steward session ended (exit {code})"})
        # the subprocess died unexpectedly - hand back any queued message the
        # user was promised, rather than orphaning it (same as stop())
        with self._lock:
            self.busy = False
            for pending in self.queue:
                self._emit({"t": "sys", "text":
                            "not delivered (session ended) - copy it back in: "
                            + pending[:120]})
            self.queue = []

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
            self.session_id = ev.get("session_id")
            _update_state(self.skey(), {"session_id": self.session_id})
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
            cost = ev.get("total_cost_usd") or 0
            usage = ev.get("usage") or {}
            self.tokens += (usage.get("input_tokens", 0)
                            + usage.get("output_tokens", 0)
                            + usage.get("cache_creation_input_tokens", 0))
            self.secs += (ev.get("duration_ms") or 0) / 1000
            self.spend += cost
            self.turns += 1
            # pinned open question: scan the WHOLE final text for the last
            # question-bearing sentence (not just a trailing "?"), so a
            # question mid-paragraph still pins. Tick turns never pin.
            txt = self.turn_text.strip()
            if not self.in_tick:
                sentences = [s.strip() for s in
                             re.split(r"(?<=[.!?])\s+", txt) if s.strip().endswith("?")]
                if sentences:
                    self.open_question = sentences[-1][-280:]
            # durable per-session usage + resume/pin state, one locked write
            _update_state(self.skey(), {
                "usage": {"spend": round(self.spend, 4), "tokens": self.tokens,
                          "secs": int(self.secs), "turns": self.turns},
                "last_text": txt[:240],
                "last_used": time.strftime("%Y-%m-%d %H:%M"),
                "cli": self.cli,
                "open_question": self.open_question,
                "epoch": self.epoch,
            })
            self.busy = False
            self._emit({"t": "turn_end",
                        "cost_usd": round(cost, 4),
                        "duration_s": round((ev.get("duration_ms") or 0) / 1000),
                        "tick": self.in_tick})
            # keep the universal status file fresh at every turn boundary so
            # the dashboard tile never shows a stale 'running' (persist only —
            # no pane block per conversational turn)
            self._status_update(emit=False)
            # tick bookkeeping under the lock - the ticker increments
            # _ticks_pending from another thread (avoid a lost update that
            # would mistag a tick turn as a normal one)
            with self._lock:
                was_tick = self.in_tick
                self.in_tick = self._ticks_pending > 0
                self._ticks_pending = max(0, self._ticks_pending - 1)
            # answer-last: John asked a literal question and this turn produced
            # only tool calls (no prose) - inject a one-shot prose nudge before
            # anything idles or drives (the failure that recurred 3x in the
            # gold session; convention -> mechanism)
            if (self._human_asked and not txt and not was_tick
                    and not self._answer_nudged and not self.general):
                self._answer_nudged = True
                self._human_asked = False
                with self._lock:
                    self._send_locked("(interface - not John) You ended without "
                                      "answering John in words. Reply now in one "
                                      "or two plain sentences.")
                return
            if txt:
                self._human_asked = False
            with self._lock:
                queued = self.queue.pop(0) if self.queue else None
                if queued is not None:
                    self._send_locked(queued)
            if queued is None:
                self._maybe_drive(was_tick)

    # ---------- proactive drive ----------
    DRIVE_CAP = 50

    def _maybe_drive(self, was_tick=False):
        """After a turn ends with nothing queued: if drive is armed, keep the
        steward moving - unless it just asked John something, the campaign
        flag says needs_you, or the cap is reached. Mechanism, not manners."""
        if not self.drive or not self.alive():
            return
        if was_tick:
            return   # a cadence-tick turn is not a step - never counts as drive
        txt = self.turn_text.strip()
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
        self._send("(drive - not John) Continue. Next step per the plan; stop "
                   "only for a decision that is genuinely John's, and if you "
                   "stop, end with the question.")

    # ---------- cadence ----------
    def _working_bg(self):
        """True when the campaign flag says commissioned/background work is
        in flight — disk truth, zero-model. The steward's own turn may be
        idle while a commissioned run (Gandalf, Foreman) works; the old
        busy-only cadence showed NOTHING for exactly the long work John
        wants to watch (handoff 2026-08-25 #2a)."""
        if self.general:
            return False
        try:
            from steward_cockpit import steward_campaign as campaign
            return campaign.read_map(self.dir)["attention"]["state"] == "working"
        except Exception:
            return False

    def _status_update(self, emit=True):
        """The 10-minute status OF RECORD — deterministic, two-part,
        zero-model (the audit's 'status treatment A' grown to commissioned
        runs). TOP: what is running now. BOTTOM: where the whole plan
        stands. Persisted to <cdir>/.ecgberht/status-summary.json — the
        UNIVERSAL file both the cockpit's right pane and the main-dashboard
        project tile read — and (emit=True) sent as a 'status' event the
        client routes to the status pane only, never the conversation."""
        if self.general:
            return
        try:
            from steward_cockpit import steward_campaign as campaign
            status = campaign.compose_status(self.dir, self.state())
        except Exception:
            return
        try:
            f = Path(self.dir) / ".ecgberht" / "status-summary.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
            os.replace(tmp, f)
        except Exception:
            pass
        # Notification-budget counter (2026-08-25 elegance S-batch, B6 bar:
        # "quiet" must be MEASURABLE): count each transition INTO needs_you —
        # the only unsolicited attention ping this engine makes — per local
        # day, durably in .ecgberht/delivery.json. Data only; no UI yet (the
        # main-dashboard attention row is its own parked prototype effort).
        try:
            cur = str(((status.get("plan") or {}).get("attention")) or "")
            prev = getattr(self, "_last_attention_state", None)
            self._last_attention_state = cur
            if cur == "needs_you" and prev not in (None, "needs_you"):
                self._delivery_patch(lambda d: d.update(
                    pings={"date": time.strftime("%Y-%m-%d"),
                           "count": (d.get("pings", {}).get("count", 0) + 1
                                     if d.get("pings", {}).get("date") == time.strftime("%Y-%m-%d")
                                     else 1)}))
        except Exception:
            pass
        if emit:
            self._emit({"t": "status", "status": status})

    # ---------- delivery receipts (2026-08-25 elegance S-batch) ----------
    #: One lock for ALL delivery.json RMWs (review finding #3: concurrent acks +
    #: the ping counter raced an unlocked read-modify-write and lost updates).
    _DELIVERY_LOCK = threading.Lock()

    def _delivery_patch(self, mutate):
        """Atomically read-modify-write <cdir>/.ecgberht/delivery.json —
        locked, with _save_state's WinError-32 retry (a concurrent reader
        holding the file must delay, never drop, the write)."""
        with StewardEngine._DELIVERY_LOCK:
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


def _tool_detail(block):
    inp = block.get("input") or {}
    name = block.get("name", "")
    for key in ("skill", "command", "description", "file_path", "prompt",
                "pattern", "query"):
        if key in inp and isinstance(inp[key], str):
            text = inp[key].replace("\n", " ")
            return text[:90] + ("..." if len(text) > 90 else "")
    return ""
