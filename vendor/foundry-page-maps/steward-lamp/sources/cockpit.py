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
import io
import json
import paths as _paths
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from steward_cockpit.question_context import (save_question_context, normalize_question_context,
                                               has_recommendation as _has_recommendation, question_line)

HERE = Path(__file__).parent
STATE_FILE = HERE / "proto-state.json"
# the 10-minute cadence (env-tunable so tests can exercise it in seconds)
TICK_SECONDS = int(os.environ.get("PROTO_TICK_SECONDS", "600"))
TICK_CHECK = max(5, min(30, TICK_SECONDS // 2))
# quiet minutes before the steward sleeps on its own (resume is seamless)
IDLE_SLEEP_SECONDS = int(os.environ.get("PROTO_IDLE_SLEEP_SECONDS", "1800"))
SILENCE_SECONDS = 4 * 3600      # a reversible decision proceeds on its recommendation after this much of John's silence
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
_CONTINUITY_PICKUP = "Read the complete durable history and give a brief pickup. "
_CONTINUITY_RULES = (
    "Continue agreed "
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
RESUME_CONTINUITY = _CONTINUITY_PICKUP + _CONTINUITY_RULES

_RESUME_REREAD = (
    "Silently re-read ECGBERHT.md, roadmap.json, strip.json, "
    "DELIVERABLES.md (the register of things worth opening - keep it current "
    "per its standing rule, and answer any 'what have we produced?' from it) "
    "and the complete durable history in .ecgberht/conversation-log.json, "
)
_RESUME_PICKUP_ASK = (
    "then give John a SHORT "
    "pickup - two or three plain sentences: where the campaign stands, the "
    "last thing that happened, and what comes next. If a question is waiting "
    "on him, restate it as the LAST line with enough context that he can "
    "answer from your words alone. "
)
_RESUME_ATTENTION = (
    " ATTENTION FLAG (2026-08-25, John saw 'waiting on you' during a live "
    "run): whenever you commission or observe background work - a "
    "researchPrime/Foreman/Gandalf run, a long build - write "
    ".ecgberht/attention.json {\"state\": \"working\", \"reason\": <what is "
    "running, plain words>} the moment it starts, and set it back to "
    "quiet the moment it lands. In managed campaigns, pending_request from "
    "refinement-update exclusively owns human wait; never stamp needs_you or "
    "Face/Strip human_wait. Legacy unmanaged campaigns retain their wait flag."
)
RESUME_BRIEF = (
    "(engine resume - not John) You are Ecgberht, waking from a parked "
    "session. " + _RESUME_REREAD + _RESUME_PICKUP_ASK + RESUME_CONTINUITY + _RESUME_ATTENTION
)

# W5 of the active set (John, 2026-10-01: "is there some type of reset for the
# steward conversation in Cave of Wonders and Campaign? That should not be the
# case"; his call: stay awake AND wake silently). The Campaign's own steward
# holds ONE conversation on the two pages: its wake puts no greeting in the
# dialogue and asks the model for no pickup - the record is re-read in silence
# and his message is answered as the conversation's next turn. The same named
# pieces as RESUME_BRIEF, the pickup asks left out (Grok W5: no slicing). A
# question that waits on him stays on the PAGE (the wake's one Open line),
# never in the model's mouth.
_RESUME_QUIET_ASK = (
    "then answer John's message as the next turn of the one conversation he "
    "sees: no pickup, no recap, no re-introduction, and never re-ask what the "
    "record answers. "
)
RESUME_QUIET = (
    "(engine resume - not John) You are Ecgberht, resuming the same "
    "conversation after a pause in the process. "
    + _RESUME_REREAD + _RESUME_QUIET_ASK + _CONTINUITY_RULES + _RESUME_ATTENTION
)
JOIN_PICKUP = "\n\nJOHN SAYS (give the short pickup first, then answer this):\n"
JOIN_QUIET = "\n\nJOHN SAYS (answer this as the next turn of the conversation):\n"

# R2 (steward responsiveness, Ecgberht journals 2069/2070, John 2026-10-04): the duty that comes first. In the Cave's
# 51-minute turn about 5 of 56 steps changed code; the rest was ceremony. Small is the default.
SMALL_DUTY = (
    "SIZE THE REQUEST FIRST. A SMALL change is a reversible change John asked for, about three files or fewer, "
    "no new effort: make the edit, run one check that can fail, commit, and reply in one or two plain sentences. "
    "For a small change write NO plan page, NO new verify or record scripts, NO report, NO DELIVERABLES row, and "
    "do not touch .ecgberht/attention.json. Anything LARGER (many files, a feature, an unknown cause, hours of work) "
    "is handed to a code job and you stay free to talk: write a short brief and run "
    "`python C:/dev/Anchor/tools/steward_code_job.py start --repo <the repo that owns the files> --brief-file <brief.md> "
    "[--check \"<a command that fails when the work is wrong>\"]`, then tell John in one line what the coder is doing. "
    "The code job runs on the best model at full effort in its own worktree, lands its work when clean, and wakes you "
    "with the result; report it in two or three sentences. While a code job runs on a repository, do not write there "
    "yourself. When John says stop, run `python C:/dev/Anchor/tools/steward_code_job.py stop`. A swarm only when he "
    "asks for one. The engine ends any small-mode turn that passes 15 tool calls. "
)

# while an effort is on (his word, or a cockpit mid-effort): the full discipline, with the hand-off for big build work
EFFORT_DUTY = (
    "THIS IS AN EFFORT: the plan discipline below applies in full. Keep the dialogue responsive: hand any long "
    "build work to a code job (`python C:/dev/Anchor/tools/steward_code_job.py start --repo <repo> --brief-file "
    "<brief.md> [--check \"<cmd>\"]`, best model, full effort, its own worktree) and tell John in one line; do "
    "not write in a repository while a code job owns it. "
)

# the coder of a code job: no steward duties, the work itself
CODER_CONTRACT = (
    "You are a code job commissioned by John's steward, not the steward: no campaign duties, no plan pages, no "
    "journals, no status files, no questions back. Do the brief completely and well, check it, and end with a plain "
    "summary of what you changed and how you checked it. "
)

_WRITE_VERBS = re.compile(r"(apply_patch|WriteAllText|WriteAllBytes|Set-Content|Add-Content|Out-File|Copy-Item|Move-Item|Remove-Item|"
                          r"New-Item|git (?:commit|merge|checkout|reset|apply|am|cherry-pick|rebase)|\bsed -i|\.write_text\(|"
                          r"\.write_bytes\(|open\([^)]*['\"][wa]['\"]|writeFileSync|(?<![=<>\-])\d?>>?\s*(?![&=>])[\w./\\$'\"~:-])", re.I)
_SHELL_TOOLS = {"exec_command", "command_execution", "Bash", "PowerShell", "shell", "local_shell_call", "exec"}
_STOP_CODER = re.compile(r"^\s*(?:please\s+)?stop (?:the )?(?:coder|code job|job)\b", re.I)
def _is_machine_text(text):
    """Queued text the engine or a code job wrote, not John's words (delivered as control: no receipt, no cap)."""
    t = str(text or "").lstrip()
    return t.startswith("(interface - not John)") or (t.startswith("(code job ") and "not John)" in t[:80])


STEP_CAP = int(os.environ.get("STEWARD_SMALL_STEP_CAP", "15"))
_EFFORT_ON = re.compile(r"\b(make (?:this|it) an effort|effort mode(?: on)?|full process|treat (?:this|it) as an effort)\b", re.I)
_EFFORT_OFF = re.compile(r"\b(small mode|effort mode off|end the effort|back to small)\b", re.I)

CONTRACT = (
    "Before framing a substantial new plan, use adaptive discovery: ask one load-bearing "
    "question at a time with context and an explicit recommendation. Usually three or four "
    "questions suffice, but never enforce a quota or a second-turn cutoff. Recover earlier "
    "answers from durable conversation history; do not repeat settled questions. Clarify "
    "shared versus group-specific work, independent acceptance and essential prerequisites "
    "where these affect the structure. Carry each answer into the same plan through the "
    "existing writer. Explain what the answer authorizes and identify the affected version. "
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
    "then one line beginning 'This authorizes:' naming the exact next act your "
    "recommendation sets in motion and, when time matters, a line 'Decide by: <when>', "
    "then a line 'Reversible: yes - undo: <how to undo it>' or 'Reversible: no' (a "
    "reversible decision proceeds on your recommendation after four hours of John's "
    "silence; an irreversible one waits for him), "
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
    "quiet the moment it lands. Managed human wait comes only from the "
    "refinement-update pending_request; never write needs_you or human_wait "
    "through attention, Face or Strip. Legacy unmanaged wait flags remain; "
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
    ""
)

# R2 (steward responsiveness, 2026-10-04): the effort rules ride only while an effort is on
EFFORT_RULES = (
    "(13) SLICE LOOP (2026-08-28): you own the overall plan. Tag every roadmap "
    "step with part=research|slice|rigor|integrate|harden (the product map is "
    "those tags, not a second file). Pass 1 of a new effort: a substantial draft "
    "covering the whole map; later passes: small slices in this session. You have "
    "NO Shark swarm — that is Crucible, only when commissioned. "
    "Commission Crucible or Foreman only when this session cannot hold the work "
    "AND the step has a gate command (a runner that can fail: tests, render-to-PNG, "
    "a certify script). After EVERY close including research, re-read the North "
    "Star and append a goal_flip event {verdict: reaffirmed|rewritten, goal_from, "
    "goal_to, step_id, goal_revision (the cockpit state's goal_revision - the hash of "
    "the North Star you re-read), scope (the closed step id), receipt}; if rewritten, "
    "update the Face. Then recommend "
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
    "optional per row). When a skill made the thing, its name is a word in the "
    "What cell, as the run hooks write it, so its mark shows in the cockpit. "
    "The Where cell is the open target - an in-effort path "
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


_GOAL_MARK = re.compile(r"\(the Campaign initiative ([A-Za-z0-9_.-]+)\)")


def _goal_in(text):
    """The goal a turn's stdin text was scoped to (by _scoped_text), or None."""
    m = _GOAL_MARK.search(str(text or ""))
    return m.group(1) if m else None


def _scoped_text(text, goal, goal_name):
    """The words as the model sees them when he speaks inside a goal's place (W2 v2): the goal named first, so a
    part, a date or a pace he mentions belongs to it. His displayed and recorded words stay his own."""
    if not goal or not goal_name:
        return text
    return "About the goal \u2018%s\u2019 (the Campaign initiative %s) \u2014 %s" % (goal_name, goal, text)


def _reported_cost(value):
    """Only an explicit, finite provider dollar figure is a reported cost."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and value >= 0:
            return float(value)
    return None


SUBSCRIPTION_CLIS = {"chatgpt": "ChatGPT", "grok": "Grok"}


def infer_subscription_cli(cli=None, usage_source=None):
    """Map a stored CLI or usage source to a subscription family, else ''."""
    family = str(cli or "").strip().lower()
    if family in SUBSCRIPTION_CLIS:
        return family
    src = str(usage_source or "").lower()
    if "codex" in src:
        return "chatgpt"
    if "grok" in src:
        return "grok"
    return ""


_LIST_PRICES = None


def api_list_prices():
    """The one dated, sourced price table (John, 2026-09-25: a subscription turn that
    reports tokens but no price carries an estimate at the provider's published API
    list price, always labeled estimated). A missing or unreadable file is {}."""
    global _LIST_PRICES
    if _LIST_PRICES is None:
        try:
            with open(os.path.join(os.path.dirname(__file__), "api_list_prices.json"), encoding="utf-8") as fh:
                _LIST_PRICES = json.load(fh)
        except Exception:
            _LIST_PRICES = {}
    return _LIST_PRICES if isinstance(_LIST_PRICES, dict) else {}


def estimate_list_price_usd(model, usage):
    """USD for one turn at the table's list price; None when the model is not in the
    table or the turn carries no token counts. Cached input is a subset of input."""
    table = api_list_prices().get("usd_per_million")
    row = (table or {}).get(str(model or "").strip().lower()) if isinstance(table, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    def count(key):
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    if not isinstance(row, dict) or not any(key in usage for key in ("input_tokens", "output_tokens")):
        return None
    try:
        cached = min(count("cached_input_tokens"), count("input_tokens"))
        return round(((count("input_tokens") - cached) * float(row["input"]) + cached * float(row["cached_input"])
                      + count("output_tokens") * float(row["output"])) / 1e6, 6)
    except (KeyError, TypeError, ValueError):
        return None


def fmt_usage_cost_text(u, cli=None):
    """Honest cost phrase. Never invents a dollar figure.

    ChatGPT/Grok subscription seats omit per-turn dollars. Those completed
    turns stay unpriced in the ledger; the visible line names the
    subscription instead of saying the account is broken or incomplete.
    """
    u = u if isinstance(u, dict) else {}
    family = infer_subscription_cli(
        cli or u.get("billing_family") or u.get("cli"),
        u.get("usage_source"))
    if str(u.get("billing_family") or "") == "mixed" or family == "mixed":
        sub_label = "ChatGPT/Grok subscription"
    else:
        sub_label = ("%s subscription" % SUBSCRIPTION_CLIS[family]) if family in SUBSCRIPTION_CLIS else ""
    unpriced = u.get("unpriced_turns")
    unpriced = unpriced if isinstance(unpriced, int) and not isinstance(unpriced, bool) and unpriced > 0 else 0
    reported = _reported_cost(u.get("reported_spend", u.get("reported_spend_usd", u.get("spend")))) or 0.0
    billed_sub = (
        u.get("billing_mode") == "subscription"
        or (bool(sub_label) and unpriced > 0 and u.get("billing_mode") != "metered")
    )
    if billed_sub and sub_label and unpriced > 0:
        turn_bit = " (%d turn%s)" % (unpriced, "" if unpriced == 1 else "s")
        if reported > 0:
            return "$%.2f previously reported · %s%s" % (reported, sub_label, turn_bit)
        return "%s%s" % (sub_label, turn_bit)
    incomplete = (
        u.get("cost_status") == "partial"
        or u.get("cost_complete") is False
        or unpriced > 0
    )
    if u.get("cost_status") == "unavailable" and reported <= 0:
        return "cost unavailable"
    if incomplete:
        if reported > 0:
            return "$%.2f reported + unpriced usage" % reported
        return "cost unavailable"
    return "$%.2f reported" % reported


def _usage_uuid(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None
    return parsed if parsed == value.lower() else None


def _usage_visibility(usage):
    """Public coverage metadata; missing historical coverage is not a zero."""
    usage = usage if isinstance(usage, dict) else {}
    status = usage.get("token_status")
    if status not in {"reported", "partial", "unavailable"}:
        status = "partial" if usage.get("tokens") else "unavailable"
    coverage = usage.get("checkpoint_coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    counts = {}
    for key in ("tracked_invocations", "reported_invocations", "partial_invocations", "unavailable_invocations", "finalized_invocations"):
        value = coverage.get(key)
        counts[key] = value if type(value) is int and value >= 0 else 0
    freshness = usage.get("usage_updated_at")
    result = {
        "token_status": status,
        "usage_source": usage.get("usage_source") or "recorded-turn-results",
        "usage_basis": usage.get("usage_basis") or "recorded-turn-results",
        "usage_updated_at": freshness if isinstance(freshness, str) else None,
        "checkpoint_coverage": counts,
    }
    pending = usage.get("unpriced_inflight")
    result["unpriced_inflight"] = pending if type(pending) is int and pending >= 0 else 0
    if usage.get("cost_status") in {"reported", "partial", "unavailable"}:
        result["cost_status"] = usage["cost_status"]
    persistence_error = usage.get("usage_persistence_error")
    result["usage_persistence_error"] = persistence_error if persistence_error == "usage-persistence-failed" else None
    attribution_error = usage.get("usage_attribution_error")
    result["usage_attribution_error"] = attribution_error if attribution_error == "usage-session-unmatched" else None
    if (result["usage_persistence_error"] or result["usage_attribution_error"]) and result["token_status"] == "reported":
        result["token_status"] = "partial"
    return result


def _usage_snapshot(usage):
    """Preserve known subtotals without certifying old, unpriced usage."""
    _usage_original = usage if isinstance(usage, dict) else {}
    # In-flight work affects visible cost coverage without inventing an
    # unpriced completed turn when a persisted checkpoint is restored.
    if type(_usage_original.get("completed_cost_complete")) is bool:
        usage = {**_usage_original, "cost_complete": _usage_original["completed_cost_complete"]}
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
    estimated = _reported_cost(u.get("estimated_spend")) or 0.0
    return {"spend": round(reported, 4) if not unknown else None,
            "reported_spend": round(reported, 4), "cost_complete": not unknown,
            "unpriced_turns": unknown, "tokens": tokens,
            "estimated_spend": round(estimated, 4), "estimated_turns": count("estimated_turns"),
            "secs": secs, "turns": turns, **_usage_visibility(_usage_original),
            **({"spend": None, "cost_complete": False} if (_usage_visibility(_usage_original)["unpriced_inflight"] or _usage_visibility(_usage_original)["usage_attribution_error"]) else {})}


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
        try:      # A4: untracked runtime state keeps its own backups (at most one per ten minutes; this file is busy)
            import paths as _paths_bk
            _paths_bk.backup_rotate(STATE_FILE, min_interval_s=600)
        except Exception:
            pass
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


STEWARD_CONVERSATION_EFFORT = (os.environ.get("ANCHOR_STEWARD_EFFORT") or "high").strip().lower()


def _cap_effort(selection, cap):
    """The selection with its effort no higher than ``cap`` (2026-10-05); unchanged when there is no cap, the cap is not a
    known level, or the selection is already at or below it."""
    import model_policy
    if not isinstance(selection, dict) or not cap or cap not in model_policy.EFFORT_ORDER:
        return selection
    eff = selection.get("effort")
    if eff not in model_policy.EFFORT_ORDER or model_policy.EFFORT_ORDER.index(eff) <= model_policy.EFFORT_ORDER.index(cap):
        return selection
    capped = dict(selection)
    capped["effort"], capped["effort_cap"] = cap, eff
    return capped


def _is_cave_dir(folder):
    """Is this the Cave of Wonders' own conversation (an effort of the Campaign, 2026-10-02)?"""
    try:
        from steward_cockpit.campaign_say import is_cave_folder
        return bool(is_cave_folder(folder))
    except Exception:
        return False


def _is_campaign_dir(folder):
    """Is this the Campaign's own folder (the steward that talks on the Cave of Wonders and the Campaign page)?"""
    try:
        from steward_cockpit.campaign_say import is_campaign_folder
        return bool(is_campaign_folder(folder))
    except Exception as e:      # the Campaign's steward would silently keep the reset: say it once in the log
        print("  [%s] ONE CONVERSATION check failed for %s: %r" % (time.strftime("%H:%M:%S"), folder, e))
        return False


def campaign_mode_name(steward):
    """The Campaign page's mode name for a persona label (John, 2026-10-03): Aladdin the Star Chart, Jarvis the
    Chart Room, Ecgberht the Beacon; "the Campaign" when the catalog cannot be read."""
    try:
        import anchor_settings as _aset
        for prof in _aset.STEWARDS.values():
            if str(prof.get("label") or "").lower() == str(steward or "").lower() and prof.get("campaign_name"):
                return str(prof["campaign_name"])
    except Exception:
        pass
    return "Campaign"


def campaign_mode_remit(steward):
    """The Campaign conversation's remit (the Star Chart, 2026-10-03): appended to the system prompt for the Campaign's
    own conversation only - never the Cave's, never a project's. The evidence it rests on is the research report's
    Adopt / Try lists (Skill Foundry planning/foundry-page-2026-10-02/research-campaign/REPORT.md)."""
    name = campaign_mode_name(steward)
    return (
        "\nTHIS CONVERSATION IS THE %s (the Campaign page in your goals-and-foresight mode; John named it). "
        "You keep your own name, %s, in what you say. Your remit here: his goals - what done looks like, their tiers, "
        "their pace, the seeds and the boneyard, each goal's guide - and foresight: what is coming, what is behind, "
        "what is starving. What the evidence supports, and you do: every goal has a specific done-when; every Tier-1 "
        "goal has ONE if-then next step in John's own words (ask him for it; never write it for him - offer options "
        "if he asks); when he sets or moves a date, plan backward from it against his own past paces on the record "
        "and say the start date that follows. Rules: John writes the words of his goals; one place nudges about any "
        "given item (a dated item within three days is the Cave of Wonders' interrupt lane, not yours to repeat); "
        "you never rank a project's next actions - that is its cockpit's work; nothing on the record moves without "
        "his word.\n"
    ) % (name.upper() if name != "Campaign" else "CAMPAIGN", steward)


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
        # W5 of the active set: the Campaign's own steward holds ONE
        # conversation (it does not park on a quiet half hour; its wake is
        # silent) - see RESUME_QUIET.
        self.one_conversation = (not general) and (_is_campaign_dir(self.dir) or _is_cave_dir(self.dir))   # the Cave's own too (2026-10-02)
        self._idle_marked = 0.0     # the quiet spell whose checkpoint is already taken
        _key = self.dir + (f"||general||{tid or 1}" if general else "")
        stored_entry = _read_state_entry(_key)
        pending_handoffs = stored_entry.get("pending_refinement_handoffs")
        self._pending_refinement_handoffs = dict(pending_handoffs) if isinstance(pending_handoffs, dict) else {}
        self._refinement_pending_lock = threading.Lock()
        self._refinement_retry_lock = threading.Lock()
        self._refinement_handoff_error = None
        import anchor_settings
        prefs = anchor_settings.load_settings()
        self.cli = stored_entry.get("cli") or prefs["default_cli"]
        self.model_selection = stored_entry.get("model_policy")
        self.policy_override = stored_entry.get("policy_override")
        # A native conversation retains its original account, including across
        # Setup edits and process restarts. New conversations use the explicit
        # Setup choice; changing settings never takes an existing bridge away.
        import provider_setup as _provider_setup
        self.provider_connection = stored_entry.get("provider_connection")
        if self.provider_connection is None:
            _family = self.cli if stored_entry.get("session_id") else prefs.get("provider_preferences", {}).get("family") or self.cli
            self.provider_connection = (_provider_setup.metadata.find_connection(prefs, _family + "-default")
                                        if stored_entry.get("session_id") else _provider_setup.selected_for_launch(prefs, _family))
        self.provider_quality = (stored_entry.get("provider_quality") if stored_entry.get("session_id") else
                                 prefs.get("provider_preferences", {}).get("quality", {}).get(self.provider_connection["family"]))
        # codex-discipline-2026-09-15 Wave 1.1 as corrected by John: the
        # dashboard selection drives every steward. What stays: a transient
        # catalog failure keeps the running family and its last selection
        # (journaled), and only a missing CLI or a dead login walks the ladder.
        self._stale_catalog_noted_at = 0.0
        # the FAMILY the background probe found unavailable (missing CLI or
        # dead login) — never a process-lifetime boolean that would walk the
        # steward off the family it failed over TO (Grok R2 N2)
        self._unavailable_family = None
        self._catalog_refresh_thread = None
        # Wave 1.2: human-first, durable ingress. The resume brief rides on his
        # next message instead of spending a turn; every send carries an
        # explicit origin; a submitted human message stays durable until the
        # broker acknowledges it with a native event.
        self._resume_prefix = None
        self._turn_origin = "human"
        self._submitted = stored_entry.get("submitted") if isinstance(stored_entry.get("submitted"), dict) else None
        self._interrupted = stored_entry.get("interrupted") if isinstance(stored_entry.get("interrupted"), dict) else None
        self._bridge_system_prompt = None
        self._project_ids = None    # (project_id, folder_path) once resolved (Wave 2 S1)
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
        self._reasked_answered = None       # an answered question the steward asked again
        self.cond = threading.Condition()
        self.busy = False
        # never-lose: restore undelivered words from the durable record so a
        # park/crash cannot drop what he already typed (2026-08-27).
        self.queue = list(stored_entry.get("pending_queue") or [])
        self.session_id = (_usage_uuid(stored_entry.get("session_id"))
            if self.cli == "chatgpt" and stored_entry.get("cli") == self.cli else None)
        # (2026-09-04, John) "the total spend tokens, time and $ resets every time I
        # reconnect with Anchor" — the counters started at zero on every engine
        # (re)creation and the turn-end write then REPLACED the durable usage with
        # the smaller in-memory total. Seed them from the record so the totals
        # carry the entire history of the effort.
        _u = _usage_snapshot(stored_entry.get("usage"))
        self.spend = _u["reported_spend"]
        self.unpriced_turns = _u["unpriced_turns"]
        self.estimated_spend, self.estimated_turns = _u["estimated_spend"], _u["estimated_turns"]
        self.tokens, self.secs, self.turns = _u["tokens"], _u["secs"], _u["turns"]
        self._restore_usage_checkpoints(stored_entry.get("usage"))
        # S2: a resumed steward's children land now, not at its next turn end;
        # the stored session serves every family (Claude binds its own later)
        self._ledger_children(_usage_uuid(stored_entry.get("session_id")))
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
        self.on_turn_done = None    # R3: a code job's report-back (called with {"text", "error"} when its turn ends)
        self.code_job = None        # R3: {"cdir", "id"} when this engine is a code job's coder
        self._turn_tools = 0        # R2: tool calls this turn (the small-mode step cap)
        self.woke_at = 0.0
        self.john_msgs = 0          # ease-metric floor: his message count
        self.open_question = stored_entry.get("open_question", "")
        self.open_question_kind = stored_entry.get("open_question_kind", "")
        self.question_context = normalize_question_context(stored_entry.get("question_context"))
        self.question_history = list(stored_entry.get("question_history") or [])
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
        if self.broken or stuck or att.get("producer_recovery_required"):
            return "red"
        # W4 of the two-lane plan (2026-10-05, his rule): ORANGE when something waits on him - even while work runs (a
        # plan ready for his review sat behind a green light on the Knowledge Map); GREEN only when work is observed
        # running - a turn, a held message, a running code job (the steward's own "working" note alone no longer
        # paints green: read_map already ages a stale note out); gray otherwise.
        if att.get("managed_refinement"):
            waits = bool(self._question_contexts(att))
        else:
            waits = bool(self.open_question) or att.get("state") in ("needs_you", "blocked")
        if waits:
            return "orange"
        if self.alive() and (self.busy or self.queue):
            return "green"
        try:
            from steward_cockpit.steward_campaign import running_code_jobs
            if running_code_jobs(self.dir):
                return "green"
        except Exception:
            pass
        if att.get("state") == "working":
            return "green"      # a fresh note (read_map keeps it only while its heartbeat is fresh)
        return "quiet"

    def _question_contexts(self, attention):
        """Conversation snapshots explain questions; the ledger still owns acceptance."""
        requests = attention.get("pending_requests") or ([attention["pending_request"]] if attention.get("pending_request") else [])
        saved = getattr(self, "question_context", None)
        contexts = []
        if saved:
            scope = saved.get("authorization_scope") or {}
            if not isinstance(scope, dict):
                scope = {}
            request_id = scope.get("request_id")
            valid = (any(r.get("id") == request_id for r in requests) if request_id else
                     not attention.get("managed_refinement") or
                     bool(scope.get("work_digest")) and scope.get("work_digest") == attention.get("work_digest"))
            if valid:
                contexts.append(saved)
        for request in requests:
            if any((q.get("authorization_scope") or {}).get("request_id") == request.get("id") for q in contexts):
                continue
            purpose = request.get("purpose") or "Review this deliverable"
            # the request's memo is the decision's source when it carries the recommendation; the record's
            # question is the memo's asking sentence, so the card shows the same shape as a conversational ask
            source = purpose if _has_recommendation(purpose) else (request.get("source_message") or purpose)
            asked = question_line(purpose) or purpose
            contexts.append(save_question_context(asked, source,
                asked_at=request.get("asked_at"), source_ref="Review request " + str(request.get("id")),
                scope={"request_id":request.get("id"), "step_id":request.get("step_id"),
                       "presentation_id":request.get("presentation_id"), "members":request.get("members", [])}))
        return contexts

    def state(self):
        import anchor_settings
        selected = anchor_settings.load_settings()
        pending = selected["default_cli"] != self.cli and not (
            self.policy_override and self.policy_override.get("revision") == selected["settings_revision"])
        attention = self._attention()
        question = self.open_question
        question_kind = self.open_question_kind
        contexts = self._question_contexts(attention)
        if attention.get("managed_refinement"):
            request = attention.get("pending_request")
            question = (request or {}).get("purpose", "")
            question_kind = "review" if request else ""
        if contexts:
            question = contexts[0]["question"]
            question_kind = "review" if (contexts[0].get("authorization_scope") or {}).get("request_id") else "decision"
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
            # Wave 1.3: how long the running turn has been quiet (no text, no
            # tool event); the busy chip retitles itself from minute 5.
            "quiet_seconds": (int(time.time() - max(self.last_output, self.turn_started))
                              if self.busy else 0),
            "session_id": self.session_id,
            "spend_usd": round(self.spend, 4) if self._usage_cost_complete() else None,
            "reported_spend_usd": round(self.spend, 4),
            "cost_status": self._usage_cost_status(),
            "unpriced_turns": self.unpriced_turns,
            "estimated_spend_usd": round(self.estimated_spend, 4),
            "estimated_turns": self.estimated_turns,
            "estimate_basis": "API list price as of %s" % (api_list_prices().get("as_of") or "an undated table"),
            "billing_mode": ("subscription" if infer_subscription_cli(self.cli, self._usage_source) and self.unpriced_turns else None),
            "cost_text": fmt_usage_cost_text({
                "reported_spend": self.spend,
                "unpriced_turns": self.unpriced_turns,
                "cost_status": self._usage_cost_status(),
                "cost_complete": self._usage_cost_complete(),
                "billing_mode": ("subscription" if infer_subscription_cli(self.cli, self._usage_source) and self.unpriced_turns else None),
                "usage_source": self._usage_source,
            }, cli=self.cli),
            "tokens": self.tokens,
            "turns": self.turns,
            **self._usage_public(),
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
            "open_question": question,
            "open_question_kind": question_kind,
            "question_context": contexts[0] if contexts else None,
            "pending_questions": contexts,
            "decision_history": [{"question": str((e.get("question") or {}).get("question") or "")[:200],
                                  "answer": str(e.get("answer") or "")[:200], "answered_at": e.get("answered_at"),
                                  "status": e.get("status"), "undo": str((e.get("question") or {}).get("undo") or "")[:200]}
                                 for e in (getattr(self, "question_history", None) or [])[-5:]],
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

    def _record_conversation(self, role, text, *, turn_id=None, goal=None):
        """The canonical project history survives provider and process changes. A turn said inside a goal's place
        (W2 v2 of the active set) carries the goal's id, so the place can show its own thread from the one log."""
        if self.fake or os.environ.get("STEWARD_COCKPIT_FAKE"):
            return True
        try:
            from steward_cockpit.conversation_history import append_turns
            turn = {"role": role, "text": text, "turn_id": turn_id or str(uuid.uuid4())}
            if goal:
                turn["goal"] = str(goal)
            append_turns(self.dir, [turn], thread_id=self._history_thread())
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
                                "model_policy": entry.get("model_policy"),
                                "provider_connection": entry.get("provider_connection"),
                                "provider_quality": entry.get("provider_quality"), "preserved_at": time.time()})
            return _update_state(self.skey(), {"provider_sessions": records}) is True

    def _desired_policy(self):
        import anchor_settings
        settings = anchor_settings.get_launch_settings()
        if not self.session_id and not self.alive() and not _read_state_entry(self.skey()).get("session_id"):
            # Opening a pane can instantiate an idle engine before Setup is
            # applied. Bind its source at the first actual launch, not that read.
            import provider_setup as _provider_setup
            family = settings.get("provider_preferences", {}).get("family") or settings["default_cli"]
            connection = _provider_setup.selected_for_launch(settings, family)
            if connection != self.provider_connection:
                self.model_selection = None
            self.provider_connection = connection
            self.provider_quality = settings.get("provider_preferences", {}).get("quality", {}).get(family)
        override = self.policy_override or {}
        # The dashboard selection drives every steward (John, 2026-09-15):
        # a newly selected model reviews the history and takes over on the
        # next message. An explicit switch carries the current revision.
        if override.get("revision") == settings["settings_revision"]:
            target = override["family"]
        else:
            self.policy_override = None
            # Setup choices apply to newly started work, not conversations
            # already bound to a native account. Global dashboard routing
            # remains its separate existing preference.
            target = (self.provider_connection["family"] if settings.get("provider_preferences", {}).get("family")
                      else settings["default_cli"])
        return settings, target

    def _note_stale_catalog(self, reason):
        """A transient catalog failure keeps the family AND the last selection;
        it is journaled (rate-limited), never a silent failover."""
        now = time.time()
        if now - self._stale_catalog_noted_at < 600:
            return
        self._stale_catalog_noted_at = now
        sel = self.model_selection or {}
        message = (f"{self.cli} capability probe failed ({reason}); keeping "
                   f"{sel.get('model', '?')}/{sel.get('effort', '?')} from the last "
                   "successful discovery (stale catalog, family kept)")
        try:
            self._journal_routing(action="stale_catalog", family=self.cli, message=message)
        except RuntimeError:
            self._emit({"t": "sys", "text": "MODEL ROUTING (not journaled): " + message})

    def _current_selection(self, settings, target):
        """The selection below, with the steward's conversation effort capped (his word, 2026-10-05: "it should be really
        responsive"; his yes to high, not maximum, for conversation turns - commissioned work keeps maximum: code jobs and
        skill runs launch with their own policy). The cap is ANCHOR_STEWARD_EFFORT (default "high"); a workbench
        terminal keeps the family's highest. Lowering it is a model refresh that keeps the native session."""
        family, selection = self._current_selection_uncapped(settings, target)
        return family, _cap_effort(selection, None if self.general else STEWARD_CONVERSATION_EFFORT)

    def _current_selection_uncapped(self, settings, target):
        """Resolve the model for the dashboard-selected family. When that is the
        family already running, a transient catalog failure keeps the last
        selection (journaled) instead of walking the family ladder; only a
        missing CLI or a dead login (found off-thread) reaches the ladder."""
        import model_policy
        if self.busy:
            return self.cli, self.model_selection
        if (self.provider_quality and target == self.provider_connection["family"]
                and self.model_selection and self.provider_quality != {"model": "latest_supported", "effort": "highest_supported"}):
            return self.cli, self.model_selection
        if not (target == self.cli and self.model_selection):
            return self._select_available_policy(settings, target)
        if self._unavailable_family == self.cli:
            failed = self.cli
            self._unavailable_family = None  # one walk per finding
            return self._select_available_policy(settings, target, excluded=(failed,))
        try:
            kwargs = self._account_policy_kwargs(self.cli)
            cached = model_policy.cached_selection(self.cli, settings=settings, **kwargs)
            if cached is not None:
                stale = cached.pop("stale", False)
                if stale:
                    # Wave 1.2: discovery runs off the request thread.
                    self._refresh_catalog_async(settings)
                return self.cli, cached
            # Cache miss (fresh process after an activation restart, Grok R1
            # F4): answer from the last persisted selection, probe off-thread.
            self._refresh_catalog_async(settings)
            return self.cli, self.model_selection
        except model_policy.PolicyUnavailable as exc:
            if exc.code in ("cli_missing", "auth_required"):
                return self._select_available_policy(settings, target, excluded=(self.cli,))
            self._note_stale_catalog(str(exc))
            return self.cli, self.model_selection
        except (ValueError, RuntimeError) as exc:
            self._note_stale_catalog(str(exc))
            return self.cli, self.model_selection

    def _refresh_catalog_async(self, settings):
        """Single-flight background discovery for the pinned family."""
        import model_policy
        thread = self._catalog_refresh_thread
        if thread is not None and thread.is_alive():
            return
        family = self.cli
        kwargs = self._account_policy_kwargs(family)

        def _run():
            try:
                model_policy.resolve(family, settings=settings, force=True, **kwargs)
            except model_policy.PolicyUnavailable as exc:
                if exc.code in ("cli_missing", "auth_required"):
                    # real capacity loss (Grok R1 F5): the next send walks the
                    # ladder instead of pretending the family still answers
                    self._unavailable_family = family
                self._note_stale_catalog(str(exc))
            except (ValueError, RuntimeError) as exc:
                self._note_stale_catalog(str(exc))
        thread = threading.Thread(target=_run, name="steward-catalog-refresh", daemon=True)
        self._catalog_refresh_thread = thread
        thread.start()

    def _account_policy_kwargs(self, family):
        if self.provider_connection["family"] == family and not self.provider_connection["native_default"]:
            import provider_native
            return {"env": provider_native.account_env(self.provider_connection)}
        return {}

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
        if settings.get("provider_preferences", {}).get("family"):
            ladder = [target]  # An explicit account choice never borrows another subscription.
        failed = []
        for family in ladder:
            if family in excluded:
                continue
            try:
                if family not in ("claude", "chatgpt", "grok"):
                    raise RuntimeError("native cockpit capability contract is not verified")
                if family == "grok" and not (HERE / "grok_turn_bridge.py").is_file():
                    raise RuntimeError("native Grok cockpit adapter is unavailable")
                if self.provider_connection["family"] == family and (not self.provider_connection["native_default"] or self.provider_quality):
                    import provider_setup as _provider_setup
                    bound_settings = {**settings, "provider_preferences": {**settings["provider_preferences"],
                                     "quality": {family: self.provider_quality} if self.provider_quality else {}}}
                    selection = _provider_setup.resolve_quality(family, bound_settings, self.provider_connection)
                else:
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
            selection = _cap_effort(selection, None if self.general else STEWARD_CONVERSATION_EFFORT)
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
        self._journal_receipt("provider_rollover", f"{old} -> {target} with a history handoff")
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
            from steward_cockpit import maintenance
            if maintenance.is_active():
                # Wave 1.6: nothing new starts behind the barrier; his words
                # are queued durably by say() and delivered after activation.
                self._emit({"t": "sys", "text": "maintenance in progress - the steward resumes after activation; your messages are kept"})
                return False, "maintenance in progress"
            return self._wake_locked(fresh, seed)

    def _wake_locked(self, fresh, seed, *, send_initial=True,
                     expected_selection=None, expected_session_id=None):
        from steward_cockpit import maintenance
        if maintenance.is_active():
            # Wave 1.6 (Grok R1 F3): every wake path, including the interrupt
            # -> wake path inside say(), stops here; queued words survive.
            self._emit({"t": "sys", "text": "maintenance in progress - the steward resumes after activation; your messages are kept"})
            return False, "maintenance in progress"
        entry = _read_state_entry(self.skey())
        is_fake = self.fake or bool(os.environ.get("STEWARD_COCKPIT_FAKE"))
        history_reference = ""
        if not is_fake:
            try:
                self._recover_legacy_history(entry)
                history_reference = self._history_reference()
                settings, target = self._desired_policy()
                import model_policy
                if expected_selection is not None:
                    if (fresh or target != expected_selection.get("family")
                            or entry.get("cli") != target
                            or entry.get("session_id") != expected_session_id):
                        raise ValueError("Model refresh policy or native session changed before wake.")
                    model_policy.validate_policy(expected_selection.get("requested_policy"))
                    model_policy.launch_args(expected_selection)
                    selection = dict(expected_selection)
                else:
                    target, selection = self._current_selection(settings, target)
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
            import provider_setup as _provider_setup
            if self.provider_connection["family"] != target:
                self.provider_connection = _provider_setup.selected_for_launch(settings, target)
                self.provider_quality = settings.get("provider_preferences", {}).get("quality", {}).get(target)
            try:
                _provider_setup.require_capacity_choice(settings, self.provider_connection)
            except ValueError as exc:
                self._emit({"t": "sys", "text": str(exc)})
                return False, str(exc)
            if not entry.get("session_id") and (not self.provider_connection["native_default"] or settings.get("provider_preferences", {}).get("quality")):
                try:
                    bound_settings = {**settings, "provider_preferences": {**settings["provider_preferences"],
                                     "quality": {target: self.provider_quality} if self.provider_quality else {}}}
                    self.model_selection = selection = _provider_setup.resolve_quality(target, bound_settings, self.provider_connection)
                except (ValueError, RuntimeError) as exc:
                    self._emit({"t": "sys", "text": "Selected provider source is unavailable: " + str(exc)})
                    return False, "selected provider source unavailable"
        held = list(entry.get("pending_queue") or [])
        if held and not self.queue:
            self.queue = held
        stored = None if fresh else entry.get("session_id")
        # a stored id from a --fake run must never be handed to the real CLI
        if stored and self.fake != bool(str(stored).startswith("fake-")):
            stored = None
        if stored and self.cli == "chatgpt" and not self.fake:
            stored = _usage_uuid(stored)
        # Bind the selected resume before its Broker can emit checkpoints or
        # an early terminal error. Fresh/provider-changed wakes clear identity.
        self.session_id = stored
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
            if not self.general and _is_campaign_dir(self.dir) and not _is_cave_dir(self.dir):
                persona += campaign_mode_remit(self.steward)      # the Star Chart's remit (2026-10-03, Grok R1 F8)
            if self.cli in ("chatgpt", "grok"):
                import sys
                bridge = "codex_turn_bridge.py" if self.cli == "chatgpt" else "grok_turn_bridge.py"
                cmd = [sys.executable, str(HERE / bridge),
                       "--target", self.dir, "--model", selection["model"],
                       "--effort", selection["effort"], "--permission-mode", self.permission_mode]
                if stored:
                    cmd += ["--resume", stored]
                self._bridge_system_prompt = persona + self._contract() + "\n" + history_reference
            elif self.cli == "claude":
                cmd = base + [
                "-p", "--verbose",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--permission-mode", self.permission_mode,
                "--disallowedTools", "AskUserQuestion",
                "--append-system-prompt", persona + self._contract() + "\n" + history_reference,
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
                env=None if is_fake else self._spawn_env(),
            )
        except Exception as e:
            self._emit({"t": "sys", "text": f"could not start the steward: {e}"})
            return False, str(e)
        self.proc = proc
        _update_state(self.skey(), {"cli": self.cli, "model_policy": self.model_selection,
                                   "provider_connection": self.provider_connection,
                                   "provider_quality": self.provider_quality,
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
                if self.cli == "chatgpt" or expected_selection is not None or entry.get("retain_native_on_resume_failure"):
                    self.proc = None
                    self._kill_tree(proc)
                    return False, "stored session could not resume; original identity retained"
                _update_state(self.skey(), {"session_id": None})
                self._emit({"t": "sys", "text":
                            "stored session could not resume - starting fresh"})
                if not self.general:
                    self._emit_resume_pickup(entry, open_only=self.one_conversation)
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
            if not self.one_conversation:
                self._emit({"t": "sys", "text": ("terminal" if self.general else "steward")
                            + " awake - resuming the last session"})
            # context on wake (John, 2026-08-25): instant deterministic pickup
            # from the durable record, then the model's own brief orientation
            # (RESUME_BRIEF also re-asserts the role - audit gap #1 - so the
            # deep campaign-memory discipline can't have drifted away).
            # The Campaign's steward (W5, 2026-10-01) wakes with neither: one
            # conversation, no greeting in the dialogue, no pickup asked - only
            # a question that waits on him is said, on the page (Grok W5).
            if not self.general:
                self._emit_resume_pickup(entry, open_only=self.one_conversation)
                # Wave 1.2: no autonomous resume turn. The brief rides on his
                # next message (human-first); an interrupted turn is reconciled
                # in the same breath.
                prefix = RESUME_QUIET if self.one_conversation else RESUME_BRIEF
                interrupted = entry.get("interrupted") if isinstance(entry.get("interrupted"), dict) else self._interrupted
                if interrupted:
                    when = time.strftime("%H:%M", time.localtime(interrupted.get("at") or time.time()))
                    prefix += (f" INTERRUPTED TURN: your previous turn was ended at {when} "
                               f"({interrupted.get('reason', 'stopped')}); its partial writes may be on disk. "
                               "Verify before repeating any action; do not assume it completed.")
                    self._interrupted = None
                    _update_state(self.skey(), {"interrupted": None})
                self._resume_prefix = prefix
                self._reconcile_submitted_locked(entry)
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
        if send_initial and initial_prompt is not None and not self._send_locked(initial_prompt, origin="control"):
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
        if send_initial and initial_prompt is None and self.queue and not self.busy:
            # Wave 1.2: a resumed steward with his words waiting delivers them
            # now (with the resume brief riding along) — no turn boundary is
            # coming to do it, because no resume turn was spent.
            self._deliver_next_queued_locked()
        return True, "awake"

    def _emit_resume_pickup(self, entry, open_only=False):
        """Deterministic context on wake — Last / Plan / Goal / Open, before
        any model turn. Zero-model, from the durable record. ``open_only``
        (the Campaign's one conversation): only a question that is actually
        waiting on him, nothing else."""
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
        wait = self._attention()
        q = ((wait.get("pending_request") or {}).get("purpose", "")
             if wait.get("managed_refinement") else (self.open_question or "")).strip()
        open_line = ("waiting on you: " + q) if q else "nothing waiting on you"
        if open_only:
            if q:
                self._emit({"t": "sys", "text": "Open: " + open_line})
            return
        self._emit({"t": "sys", "text": "Last time: " + outcome})
        self._emit({"t": "sys", "text": "Plan: " + plan})
        self._emit({"t": "sys", "text": "Goal: " + goal_line})
        self._emit({"t": "sys", "text": "Open: " + open_line})

    def stop(self):
        # commit-as-you-go covers an explicit Sleep / shutdown too (finding #4
        # gap): a steward's dirty tree is committed before it parks
        if not self.general and self.alive():
            self._commit_if_dirty("steward checkpoint on sleep")
        # Wave 1.6: close stdin UNDER the ingress lock so a concurrent say()
        # can never be mid-write when the pipe goes away ("delivery failed",
        # broken=True); the wait itself stays outside the lock.
        with self._lock:
            proc = self.proc
            closing = proc is not None and proc.poll() is None
            if closing:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
        if closing and self.busy:
            self._journal_receipt("steward_stopped", "stopped while a turn was running")
        if closing:
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
    def say(self, text, human=True, question_id=None, goal=None):
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty"}
        if human:   # W1 of the two-lane plan (2026-10-05): the queue wait is measured from his message's arrival
            self._human_arrivals = (getattr(self, "_human_arrivals", None) or [])[-20:] + [time.time()]
        goal = str(goal or "").strip() or None      # W2 v2: said inside a goal's place — recorded with the tag, sent with the scope
        goal_name = ""
        if goal:
            try:
                from steward_cockpit import campaign_acts as _acts
                _g = _acts._step(self.dir, goal)
                goal_name = str((_g or {}).get("name") or "")
            except Exception:
                goal_name = ""
            if not goal_name:
                goal = None
        if human and not self.general and not self.code_job:
            # R2/R3 (2026-10-04): his words set the mode and stop a code job; the message still goes to the steward
            if _EFFORT_ON.search(text) or _EFFORT_OFF.search(text):
                on = bool(_EFFORT_ON.search(text))
                _update_state(self.skey(), {"effort_mode": on})
                self._emit({"t": "sys", "text": "effort rules on - the full plan discipline applies here" if on else "small mode - small changes stay small; real work goes to a code job"})
            if _STOP_CODER.match(text):
                try:
                    from steward_cockpit import code_jobs as _cj
                    from steward_cockpit import steward_routes as _sr
                    r = _cj.stop(self.dir, engine_lookup=lambda wt: _sr.get_engine(wt, general=True, tid="1", create=False))
                    self._emit({"t": "sys", "text": ("code job stopped; its work so far stays on branch " + r["branch"]) if r.get("ok") else ("no code job to stop: " + str(r.get("error")))})
                except Exception as e:
                    self._emit({"t": "sys", "text": "the code job could not be stopped: %s" % e})
        answer_context = None
        if question_id:
            answer_context = next((q for q in self._question_contexts(self._attention()) if q["id"] == question_id), None)
            if not answer_context:
                return {"ok": False, "error": "This question changed or was resolved. Open the current question before answering."}
        if not self.alive():
            ok, why = self.wake()
            if not ok:
                from steward_cockpit import maintenance
                if human and maintenance.is_active():
                    # Wave 1.6: accepted durably, delivered after activation.
                    with self._lock:
                        if not self._record_conversation("john", text, goal=goal):
                            return {"ok": False, "error": "your message was not accepted because durable conversation storage failed"}
                        self.queue.append(_scoped_text(text, goal, goal_name))
                        if not self._persist_queue():
                            self.queue.pop()
                            return {"ok": False, "error": "could not durably queue your text"}
                        self._emit({"t": "john", "text": text})
                        self._emit({"t": "sys", "text": "queued - maintenance in progress; delivered when the steward resumes"})
                    return {"ok": True, "queued": True, "maintenance": True}
                if human:
                    # W2e (2026-09-30, John: "not delivered - your text is back in the box" after a restart): a wake that
                    # failed (the provider deferred, the settings unreadable, the CLI gone) keeps his words durably; they
                    # go on the next wake - never his to retype. A control that cannot be delivered is simply not sent.
                    with self._lock:
                        if not self._record_conversation("john", text, goal=goal):
                            return {"ok": False, "error": "your message was not accepted because durable conversation storage failed"}
                        self.queue.append(_scoped_text(text, goal, goal_name))
                        if not self._persist_queue():
                            self.queue.pop()
                            return {"ok": False, "error": "could not durably queue your text"}
                        self._emit({"t": "john", "text": text})
                        self._emit({"t": "sys", "text": "the steward could not wake just now (" + str(why) + ") - your text is kept and goes when it wakes"})
                    return {"ok": True, "queued": True, "kept": True}
                return {"ok": False, "error": why}

        # One ingress transaction: update the human/control state, append the
        # visible event, and either queue or write stdin under the same lock as
        # result-boundary arbitration. A displayed human turn therefore can
        # never be followed by an automatic nudge/drive write before it lands.
        wait = self._attention() if human else {}
        with self._lock:
            control = ""
            if human:
                if question_id and not any(q["id"] == question_id for q in self._question_contexts(wait)):
                    return {"ok": False, "error": "Question is no longer current"}
                if not self._record_conversation("john", text, goal=goal):
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
                if answer_context:
                    entry = {"question":answer_context, "answer":text, "answered_at":time.time(),
                             "status":"response_recorded", "source_ref":"Cockpit conversation"}
                    history = (getattr(self, "question_history", []) + [entry])[-100:]
                    if not _update_state(self.skey(), {"question_history":history}):
                        return {"ok": False, "error": "Question response context could not be saved"}
                    self.question_history = history
                    if not (answer_context.get("authorization_scope") or {}).get("request_id"):
                        self._strip_clear_wait()    # a decision answered: the wait on John is over (C2)
                        try:
                            from . import horizon as _horizon
                            _horizon.refresh(self.dir, "answered")   # W3 (2026-09-28): the line follows the answer
                        except Exception:
                            pass

                if wait.get("managed_refinement"):
                    # Conversation and drive controls never resolve a review.
                    # Only a lifecycle operation can change its pending request.
                    self.open_question = ""
                    self.open_question_kind = ""
                    if control and self._question_contexts(wait):
                        self._emit({"t": "john", "text": text})
                        return {"ok": True, "queued": False, "control_only": True}
                elif self.open_question:
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
                        "question_context": None,
                    })
                if not control:
                    self.question_context = None
                    _update_state(self.skey(), {"question_context":None})

            self._emit({"t": "john" if human else "sys", "text": text})
            text = _scoped_text(text, goal, goal_name)      # the model is told which goal he is in; his shown words stay his own
            if answer_context:
                text += ("\n\n(answer context, not a new request) This response concerns only the saved question and "
                         "versions below. Recheck applicability before acting; this is not automatic acceptance.\n" +
                         json.dumps(answer_context, ensure_ascii=False))
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
                if human and self._turn_origin != "human":
                    # Wave 1.2: his words outrank a self-started turn (drive,
                    # nudge, stand-up). The turn is ended, its outcome recorded
                    # as uncertain, and his message goes next.
                    self._emit({"t": "sys", "text": "your message arrived during a self-started turn - ending that turn; your message goes next"})
                    self._interrupt_turn_locked("human message arrived during a self-started turn")
                    ok, why = self._wake_locked(fresh=False, seed=None)
                    if not ok:
                        self._emit({"t": "sys", "text": "steward could not resume after the interruption: " + str(why) + "; your message is queued"})
                    return {"ok": True, "queued": bool(self.queue), "interrupted": True}
                # R1 (steward responsiveness, 2026-10-04): the receipt names what the steward is on and since
                # when, and carries "Take this now" (interrupt, then deliver his message at once)
                if human:
                    self._emit({"t": "sys", "text": self._queued_receipt(), "take_now": True})
                else:
                    self._emit({"t": "sys", "text": "queued - the steward is mid-turn; it will be delivered next"})
                return {"ok": True, "queued": True}
            from steward_cockpit import maintenance
            if human and maintenance.is_active():
                # Wave 1.6 (Grok R1 F3): an alive, idle steward behind the
                # barrier takes no new turn; his words wait durably.
                self.queue.append(text)
                if not self._persist_queue():
                    self.queue.pop()
                    return {"ok": False, "error": "could not durably queue your text"}
                self._emit({"t": "sys", "text": "queued - maintenance in progress; delivered when the steward resumes"})
                return {"ok": True, "queued": True, "maintenance": True}
            ok = self._send_locked(text + (self._plan_drift_suffix() if (human and not self.general and self.effort_on()) else ""),
                                   origin="human" if human else "control")
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

    def _refresh_model_locked(self, selection):
        """Replace an idle bridge while retaining its native session and queued work."""
        import model_policy
        if self.busy:
            return False
        current = self.model_selection or {}
        if selection.get("family") != self.cli:
            raise ValueError("A model refresh must retain the current provider family.")
        if all(current.get(key) == selection.get(key) for key in ("family", "model", "effort")):
            return True

        stored = self.session_id
        if not isinstance(stored, str) or not stored.strip():
            raise ValueError("Model refresh requires the existing native session ID.")
        if self.cli == "chatgpt":
            from uuid import UUID
            try:
                UUID(stored)
            except (ValueError, AttributeError) as exc:
                raise ValueError("Model refresh requires a valid Codex thread UUID.") from exc
        model_policy.validate_policy(selection.get("requested_policy"))
        model_policy.launch_args(selection)
        _, target = self._desired_policy()
        if target != self.cli:
            raise ValueError("Provider family changed before the idle model refresh.")
        if not _update_state(self.skey(), {
                "cli": self.cli, "model_policy": self.model_selection,
                "policy_override": self.policy_override, "session_id": stored,
                "retain_native_on_resume_failure": True}):
            raise RuntimeError("Could not persist the native session before model refresh.")
        self._journal_routing(
            action="model_refresh",
            message="Refreshing the next turn's model and effort while retaining its native session.",
            family=self.cli, session_id=stored,
            previous_model=current.get("model"), previous_effort=current.get("effort"),
            requested_model=selection.get("model"), requested_effort=selection.get("effort"))

        queued = list(self.queue)
        old_proc = self.proc
        self.proc = None  # A retiring reader must not mark the replacement broken.
        if old_proc is not None:
            self._kill_tree(old_proc)
        try:
            ok, note = self._wake_locked(
                fresh=False, seed=None, send_initial=False,
                expected_selection=selection, expected_session_id=stored)
        finally:
            self.queue[:] = queued
        if not ok:
            # Restore only the idle transport, without submitting a model turn.
            # The next actual send must still resolve latest/highest policy.
            restored, restore_note = self._wake_locked(
                fresh=False, seed=None, send_initial=False,
                expected_selection=current, expected_session_id=stored)
            self.queue[:] = queued
            self._emit({"t": "sys", "text":
                        "Previous idle transport restored; request retained." if restored else
                        "Native session retained; transport recovery remains unavailable: " + str(restore_note)})
            raise RuntimeError("Idle model refresh failed: " + str(note))
        if self.cli != selection.get("family") or self.session_id != stored:
            replacement = self.proc
            self.proc = None
            if replacement is not None:
                self._kill_tree(replacement)
            self.busy = False
            raise RuntimeError("Idle model refresh did not retain the native session.")
        return True

    def _send_locked(self, text, *, origin=None):
        """Caller holds self._lock. Returns True iff the write reached stdin.

        ``origin`` (Wave 1.2): "human" for John's words, "control" for engine
        prompts. Explicit, never inferred from a leading "(" — the resume
        prefix starts with one and must still be treated as his message.
        """
        from steward_cockpit import maintenance
        if maintenance.is_active():
            # Wave 1.6: nothing new is written to a steward behind the barrier.
            # Human words are queued by say(); controls are simply not sent.
            if time.time() - getattr(self, "_maintenance_noted_at", 0.0) > 60:
                self._maintenance_noted_at = time.time()
                self._emit({"t": "sys", "text": "maintenance in progress - nothing new is sent to the steward until activation"})
            return False
        human_text = text  # the durability identity: his words, never the wrapper
        if origin == "human" and self._resume_prefix:
            text = (self._resume_prefix
                    + (JOIN_QUIET if self._resume_prefix.startswith(RESUME_QUIET) else JOIN_PICKUP) + text)
            self._resume_prefix = None
        if not (self.fake or os.environ.get("STEWARD_COCKPIT_FAKE")):
            try:
                settings, target = self._desired_policy()
            except (ValueError, RuntimeError) as exc:
                self._emit({"t": "sys", "text": "Model settings unavailable; message not sent: " + str(exc)})
                return False
            if target != self.cli:
                if self.busy:
                    self._emit({"t": "sys", "text":
                                "Provider refresh deferred until the current turn finishes; message not sent."})
                    return False
                return self._rollover_locked(target, settings, text)
            try:
                target, selection = self._current_selection(settings, target)
                if target != self.cli:
                    if self.busy:
                        self._emit({"t": "sys", "text":
                                    "Provider refresh deferred until the current turn finishes; message not sent."})
                        return False
                    return self._rollover_locked(target, settings, text)
                current = self.model_selection or {}
                changed = any(current.get(key) != selection.get(key)
                              for key in ("family", "model", "effort"))
                if changed:
                    if self.busy:
                        self._emit({"t": "sys", "text":
                                    "Model refresh deferred until the current turn finishes; message not sent."})
                        return False
                    if not self._refresh_model_locked(selection):
                        return False
            except (ValueError, RuntimeError) as exc:
                self._emit({"t": "sys", "text":
                            "Model refresh unavailable; message not sent: " + str(exc)})
                return False
        proc = self.proc
        msg = {"type": "user",
               "message": {"role": "user",
                           "content": [{"type": "text", "text": text}]}}
        if self._bridge_system_prompt:
            msg["system_prompt"] = self._bridge_system_prompt
        if self.cli in ("chatgpt", "grok"):
            msg["standing_rules"] = self._contract()   # every bridge turn is a new process: the rules ride each one
            if not self.general and _is_campaign_dir(self.dir) and not _is_cave_dir(self.dir):
                # the Star Chart's remit rides every bridge turn too, resumed or not (Grok code R1 F4)
                msg["standing_rules"] = campaign_mode_remit(self.steward) + self._contract()
        # No CLI call under the stdin arbiter. A producer captures its exact
        # context through the lifecycle CLI; automatic fallback remains unknown.
        refinement_context = None
        refinement_producer_id = None
        if origin is None:
            is_control = text in (TICK, REASSERT) or text.startswith("(")
        else:
            is_control = origin != "human"
        if not self.busy and not is_control and (Path(self.dir) / "roadmap.json").is_file():
            from steward_cockpit.producer_handoff import _handoff_id
            refinement_producer_id = uuid.uuid4().hex
            handoff_id = _handoff_id("conversation", refinement_producer_id)
            msg["message"]["content"][0]["text"] += (
                "\n\n(interface bookkeeping, not a new user request) If this campaign is managed "
                "and this turn produces deliverables, capture dispatch context before producing "
                "them, and use producer_handoff id " + handoff_id +
                " with producer_kind conversation. Record explicit output references through "
                "the lifecycle CLI and preserve current cumulative feedback. Leave the handoff "
                "pending for a later inspection of the outputs. Pure inspection and bookkeeping "
                "do not produce a new handoff. Never close "
                "a slice without John's explicit instruction.")
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            self._bridge_system_prompt = None
            self._last_submitted = text
            self._turn_had_tools = False
            if not self.busy:
                self._turn_tools = 0
                self._turn_wrote_files = False
                self._turn_output_refs = []
                self._refinement_dispatch_context = refinement_context
                self._refinement_producer_id = refinement_producer_id
            self.busy = True
            self.turn_started = time.time()
            self.turn_text = ""
            self._turn_origin = "control" if is_control else "human"
            arrivals = getattr(self, "_human_arrivals", None) or []
            self._timing = {"arrived": (arrivals.pop(0) if (arrivals and not is_control) else None),
                            "started": self.turn_started, "first_word": None, "tools": 0}
            if not is_control:
                # Wave 1.2: durable until the broker's first native event acks
                # it; reconciled on the next wake if the process dies first.
                # Stored as HIS text (pre-prefix): the resume wrapper already
                # sits in every earlier resume turn of the same thread and
                # would false-match the rollout (Grok R1 F1).
                self._submitted = {"text": human_text[:4000], "at": time.time(),
                                   "family": self.cli, "session_id": self.session_id}
                _update_state(self.skey(), {"submitted": self._submitted})
            return True
        except Exception as e:
            self.broken = True
            self._emit({"t": "sys", "text": f"delivery failed: {e}"})
            return False

    def _deliver_next_queued_locked(self):
        """Deliver the head of the durable queue as John's words (drift line
        computed NOW, at delivery — journal 0111). Caller holds self._lock."""
        if not self.queue or self.busy:
            return False
        from steward_cockpit import maintenance
        if maintenance.is_active():
            return False  # Wave 1.6: held until activation
        queued = self.queue[0]
        machine = _is_machine_text(queued)
        suffix = "" if (self.general or machine or not self.effort_on()) else self._plan_drift_suffix()
        if self._send_locked(queued + suffix, origin="control" if machine else "human"):
            self.queue.pop(0)
        if not self._persist_queue():
            self.broken = True
            self._emit({"t": "sys", "text":
                        "queue state could not be persisted after "
                        "delivery - delivery is uncertain across "
                        "a restart"})
        return True

    def _reconcile_submitted_locked(self, entry):
        """Wave 1.2: a human message written to a broker that died before any
        native event acknowledged it is re-queued with a repeat marker. Never
        lost; a repeat is marked so the model does not act on it twice. (A
        provider-record scan was cut as a second mechanism — Rabbit-Catcher.)"""
        sub = entry.get("submitted") if isinstance(entry.get("submitted"), dict) else self._submitted
        if not sub or not sub.get("text"):
            self._submitted = None
            return
        marker = ("(possibly a repeat after a restart or interruption; if you already "
                  "handled this, say so in one line and do nothing else) ")
        if not any(q.endswith(sub["text"]) for q in self.queue):
            self.queue.insert(0, marker + sub["text"])
        self._emit({"t": "sys", "text": "a message submitted before the last interruption was re-queued with a repeat marker"})
        self._submitted = None
        _update_state(self.skey(), {"submitted": None, "pending_queue": list(self.queue)})

    def _interrupt_turn_locked(self, reason):
        """Wave 1.2/1.3: end the running turn. The exec protocol has no
        retractable item boundary, so the outcome is recorded as uncertain;
        partial writes stay on disk; the queue and the native thread are kept."""
        proc = self.proc
        if proc is None or proc.poll() is not None or not self.busy:
            return {"ok": False, "error": "no running turn"}
        origin = getattr(self, "_turn_origin", "human")
        self._interrupted = {"at": time.time(), "reason": reason, "origin": origin,
                             "text": (self._last_submitted or "")[:300]}
        _update_state(self.skey(), {"interrupted": self._interrupted})
        self._emit({"t": "sys", "text": f"turn interrupted ({reason}); partial work on disk is kept and the outcome is uncertain until the next turn reconciles it"})
        try:
            self._journal_routing(action="interrupted", family=self.cli, origin=origin,
                                  message=f"turn interrupted: {reason} (origin {origin}); outcome uncertain")
        except RuntimeError:
            pass
        self.proc = None   # the old reader must not touch shared state
        self._kill_tree(proc)
        self.busy = False
        self._hold_queue("turn interrupted")
        return {"ok": True}

    def effort_on(self):
        """R2: the effort rules ride while an effort is on: John's word ("make this an effort" / "small mode") wins;
        else a project cockpit whose plan has an open step is an effort; the Cave and the Star Chart conversations
        (one_conversation) and workbench terminals are small by default."""
        entry = _read_state_entry(self.skey())
        if isinstance(entry.get("effort_mode"), bool):
            return entry["effort_mode"]
        if self.general or self.one_conversation or self.code_job:
            return False
        # his word not given: a project cockpit with a step in progress NOW is mid-effort (read fresh, never stored)
        try:
            rm = json.loads((Path(self.dir) / "roadmap.json").read_text(encoding="utf-8"))
            steps = rm.get("roadmap_projection") if isinstance(rm, dict) else None
            return any(isinstance(x, dict) and str(x.get("status") or "") in ("active", "in_progress", "running")
                       for x in (steps or []))
        except Exception:
            return False

    def _contract(self):
        if self.code_job:
            return CODER_CONTRACT
        if self.effort_on():
            return EFFORT_DUTY + CONTRACT + EFFORT_RULES
        return SMALL_DUTY + CONTRACT

    def _fire_turn_done(self, result):
        cb, self.on_turn_done = self.on_turn_done, None
        if cb is None:
            return
        try:
            cb(result)
        except Exception:
            pass

    def _guard_turn(self, block):
        """R2/R3: end a small-mode turn that has grown past the step cap (it is handed to a code job), and a turn
        that writes into a repository a running code job owns (one writer). True when the turn was ended."""
        if self.general or self.code_job or self.fake or not self.busy:
            return False
        reason, note = "", ""
        inp = block.get("input") or {}
        paths = [p for p in ([inp.get("file_path")] + list(inp.get("paths") or [])) if isinstance(p, str) and p.strip()]
        try:
            from steward_cockpit import code_jobs as _cj
            owned = _cj.active_repos()
        except Exception:
            owned = []
        hit = []
        if owned:
            name = block.get("name") or ""
            absolute = [p if os.path.isabs(p) else os.path.join(self.dir, p) for p in paths]
            if name in ("Write", "Edit", "NotebookEdit", "file_change", "apply_patch"):
                hit = [p for p in absolute if any(_cj.inside(p, r) for r in owned)]
            elif name in _SHELL_TOOLS:
                # a shell or exec call: a write when it runs inside a busy repository, or names one with a writing verb
                cmd = json.dumps(inp, ensure_ascii=False)[:6000]
                if any(_cj.inside(self.dir, r) for r in owned) and _WRITE_VERBS.search(cmd):
                    hit = [self.dir]
                else:
                    flat = cmd.replace("\\\\", "/").replace("\\", "/").lower()
                    for r in owned:
                        rr = str(r).replace("\\", "/").lower().rstrip("/")
                        if re.search(re.escape(rr) + r"(?:/|[\"' ]|$)", flat) and _WRITE_VERBS.search(cmd):
                            hit = [r]
                            break
            if hit:
                reason = "one writer: a code job is working on that repository"
                note = ("(interface - not John) Your last turn was ended: it wrote %s while a code job owns that "
                        "repository. Do not write there until the job reports; tell John in one line." % hit[0])
        if not reason and getattr(self, "_turn_origin", "human") == "human" and self._turn_tools > STEP_CAP and not self.effort_on():
            reason = "past %d tool calls: larger than a small change" % STEP_CAP
            note = ("(interface - not John) Your last turn was ended after %d tool calls: this is larger than a small "
                    "change. Hand it to a code job now (tools/steward_code_job.py start, with a short brief and a check), "
                    "then tell John in one line what the coder is doing." % self._turn_tools)
        if not reason:
            return False
        with self._lock:
            self._emit({"t": "sys", "text": "%s ended its turn (%s)" % (self.steward or "The steward", reason)})
            out = self._interrupt_turn_locked(reason)
            if isinstance(out, dict) and out.get("ok"):
                self.queue.insert(0, note)
                self._persist_queue()
                self._wake_locked(fresh=False, seed=None)
        return True

    def _turn_activity(self):
        """What the running turn is on, in its own words: the first sentence the steward spoke this turn, else his
        message it is answering."""
        said = " ".join(str(getattr(self, "turn_text", "") or "").split())
        if said:
            first = re.split(r"(?<=[.!?])\s", said, maxsplit=1)[0]
            return first[:110] + ("\u2026" if len(first) > 110 else "")
        asked = " ".join(str(getattr(self, "_last_submitted", "") or "").split())
        asked = re.sub(r"^\(.*?\)\s*", "", asked)
        return ("your message \u201c%s\u201d" % (asked[:80] + ("\u2026" if len(asked) > 80 else ""))) if asked else "a turn"

    def _queued_receipt(self):
        started = getattr(self, "turn_started", 0) or 0
        since = ""
        if started:
            mins = int(max(0, time.time() - started) // 60)
            since = ", since %s (%d min)" % (time.strftime("%H:%M", time.localtime(started)), mins)
        ahead = max(0, len(self.queue) - 1)
        nxt = "Your message is next." if not ahead else "Your message is queued after %d other%s." % (ahead, "" if ahead == 1 else "s")
        return "%s is on: %s%s. %s" % (self.steward or "The steward", self._turn_activity(), since, nxt)

    def take_now(self):
        """R1: his "Take this now" - the running turn ends (outcome uncertain, partial work kept, as a Stop turn) and
        the steward wakes on the same thread to answer the queue at once, the sequence the self-started branch of
        say() already uses."""
        with self._lock:
            if not (self.busy and self.queue):
                return {"ok": False, "error": "nothing is waiting behind a running turn"}
            out = self._interrupt_turn_locked("John: take this now")
            if not (isinstance(out, dict) and out.get("ok")):
                return out
            ok, why = self._wake_locked(fresh=False, seed=None)
            if not ok:
                self._emit({"t": "sys", "text": "steward could not resume after the interruption: " + str(why) + "; your message is queued"})
        try:
            self._journal_receipt("turn_interrupted", "John: take this now")
        except Exception:
            pass
        return {"ok": bool(ok), "why": "" if ok else str(why)}

    def interrupt_turn(self, reason="stopped by John"):
        with self._lock:
            out = self._interrupt_turn_locked(reason)
        if isinstance(out, dict) and out.get("ok"):
            self._journal_receipt("turn_interrupted", reason)
        return out

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
            # R3 (Grok code F4): a coder that dies without a result still finishes its job, as a failure
            if self.on_turn_done is not None:
                self._fire_turn_done({"text": self.turn_text.strip(), "error": "the coder's session ended (exit %s) without a result" % code})
        self._status_update(emit=True)

    def _read_stderr(self, proc):
        tail = []
        for line in proc.stderr:
            tail.append(line.strip())
            if len(tail) > 20:
                tail.pop(0)
        if (proc is self.proc and tail
                and proc.poll() not in (0, None)):
            # Wave 1.3 (Grok R1 F7): this pipe is the bridge's or the native
            # CLI's own stderr — it can carry login URLs. Kinds only.
            try:
                from steward_cockpit.codex_turn_bridge import classify_stderr
                hint = classify_stderr(tail)
                text = ("engine stderr: " + ", ".join(hint["kinds"][:4])
                        + f" ({hint['lines']} lines, content withheld)")
            except Exception:
                text = f"engine stderr: {len(tail)} lines (content withheld)"
            self._emit({"t": "sys", "text": text})

    def _restore_usage_checkpoints(self, stored):
        stored = stored if isinstance(stored, dict) else {}
        records = stored.get("usage_checkpoints")
        records = records if isinstance(records, dict) else {}
        self._usage_checkpoints = {}
        self._usage_legacy_unknown = bool(stored.get("usage_legacy_unknown", bool(self.tokens or self.turns)))
        self._usage_legacy_reported = stored.get("usage_legacy_reported") is True
        for invocation_id, record in records.items():
            if _usage_uuid(invocation_id) is None or not isinstance(record, dict):
                self._usage_legacy_unknown = True
                continue
            valid_credit = type(record.get("credited_tokens")) is int and record["credited_tokens"] >= 0
            valid_session = _usage_uuid(record.get("session_id")) is not None
            counts = record.get("counts")
            valid_counts = counts is None or self._usage_counts(counts) == counts
            if counts is not None and valid_counts and valid_credit:
                valid_counts = counts["input_tokens"] + counts["output_tokens"] == record["credited_tokens"]
            if counts is None and valid_credit and record["credited_tokens"]:
                valid_counts = False
            if not valid_credit or not valid_session or not valid_counts or type(record.get("finalized")) is not bool:
                # Preserve an unusable ID as a quarantine, rather than allow a
                # replay to credit the same invocation over the saved total.
                self._usage_checkpoints[invocation_id] = {"invalid": True, "token_status": "unavailable"}
                self._usage_legacy_unknown = True
                continue
            self._usage_checkpoints[invocation_id] = dict(record)
        self._usage_source = stored.get("usage_source") or "recorded-turn-results"
        self._usage_updated_at = stored.get("usage_updated_at")
        self._usage_persistence_error = ("usage-persistence-failed"
            if stored.get("usage_persistence_error") == "usage-persistence-failed" else None)
        self._usage_attribution_error = ("usage-session-unmatched"
            if stored.get("usage_attribution_error") == "usage-session-unmatched" else None)
        self._usage_attribution_warned = False

    def _usage_public(self, *, persistence_confirmed=False):
        records = tuple(record for record in tuple(self._usage_checkpoints.values()) if not record.get("invalid"))
        coverage = {"tracked_invocations": len(records), "reported_invocations": 0,
                    "partial_invocations": 0, "unavailable_invocations": 0,
                    "finalized_invocations": 0}
        verified = self._usage_legacy_reported or self.tokens > 0
        persistence_error = None if persistence_confirmed else self._usage_persistence_error
        partial = self._usage_legacy_unknown or persistence_error is not None or self._usage_attribution_error is not None
        for record in records:
            status = record.get("token_status", "unavailable")
            if status not in {"reported", "partial", "unavailable"}:
                status = "unavailable"
            coverage[status + "_invocations"] += 1
            coverage["finalized_invocations"] += record.get("finalized") is True
            verified = verified or record.get("counts") is not None
            partial = partial or status != "reported" or record.get("finalized") is not True
        status = "partial" if verified and partial else "reported" if verified else "unavailable"
        return {"token_status": status, "usage_source": self._usage_source,
                "usage_updated_at": self._usage_updated_at,
                "usage_basis": "recorded-turn-results-and-invocation-checkpoints" if records else "recorded-turn-results",
                "checkpoint_coverage": coverage,
                "usage_persistence_error": persistence_error,
                "usage_attribution_error": self._usage_attribution_error,
                "unpriced_inflight": sum(record.get("finalized") is not True for record in records)}

    def _usage_cost_complete(self):
        return not self.unpriced_turns and not self._usage_attribution_error and not any(record.get("finalized") is not True for record in tuple(self._usage_checkpoints.values()) if not record.get("invalid"))

    def _usage_cost_status(self):
        if self._usage_cost_complete():
            return "reported"
        return "partial" if self.spend or self.turns > self.unpriced_turns else "unavailable"

    def _usage_payload(self, *, persistence_confirmed=False):
        # No lock here: accounting persistence already holds _lock, while
        # read-only callers need a snapshot without acquiring it recursively.
        return {"spend": round(self.spend, 4) if self._usage_cost_complete() else None,
                "reported_spend": round(self.spend, 4), "cost_complete": self._usage_cost_complete(),
                "completed_cost_complete": not self.unpriced_turns,
                "cost_status": self._usage_cost_status(),
                "unpriced_turns": self.unpriced_turns, "tokens": self.tokens,
                "estimated_spend": round(self.estimated_spend, 4), "estimated_turns": self.estimated_turns,
                "secs": int(self.secs), "turns": self.turns,
                **self._usage_public(persistence_confirmed=persistence_confirmed),
                "usage_legacy_unknown": self._usage_legacy_unknown,
                "usage_legacy_reported": self._usage_legacy_reported,
                "usage_checkpoints": {key: dict(value) for key, value in self._usage_checkpoints.items()}}

    def _persist_usage_locked(self):
        """Write the complete aggregate once; retain memory on save failure."""
        was_failed = self._usage_persistence_error is not None
        try:
            saved = _update_state(self.skey(), {"usage": self._usage_payload(persistence_confirmed=True)}) is True
        except Exception:
            saved = False
        self._usage_persistence_error = None if saved else "usage-persistence-failed"
        return saved, not saved and not was_failed

    def _warn_usage_persistence(self, warning):
        if warning:
            self._emit({"t": "sys", "text": "Usage totals could not be saved. The displayed counts are in memory and may be lost on restart."})

    def _usage_identity(self, ev, *, final=False):
        key = "usage_invocation_id" if final else "invocation_id"
        invocation_id = _usage_uuid(ev.get(key))
        session_id = _usage_uuid(ev.get("session_id"))
        active_session = _usage_uuid(self.session_id)
        if invocation_id is None or session_id is None or session_id != active_session:
            return None
        record = self._usage_checkpoints.get(invocation_id)
        if record is not None and (record.get("invalid") or record.get("session_id") != session_id):
            return None
        return invocation_id, session_id, record

    def _usage_result_allowed(self, ev):
        if "usage_invocation_id" not in ev:
            return True  # Legacy providers retain their original accounting.
        warning = False
        with self._lock:
            identity = self._usage_identity(ev, final=True)
            # A completed duplicate can be dropped. An owned result whose
            # usage identity is missing/foreign must still finish the turn.
            allowed = identity is None or not (identity[2] or {}).get("finalized")
            if identity is not None and not allowed and self._usage_persistence_error:
                _, warning = self._persist_usage_locked()
        self._warn_usage_persistence(warning)
        return allowed

    @staticmethod
    def _usage_counts(usage, previous=None):
        if not isinstance(usage, dict):
            return None
        previous = previous if isinstance(previous, dict) else {}
        counts = {"input_tokens": usage.get("input_tokens"),
                  "output_tokens": usage.get("output_tokens"),
                  "cached_input_tokens": usage.get("cached_input_tokens", previous.get("cached_input_tokens", 0))}
        if any(type(value) is not int or value < 0 for value in counts.values()):
            return None
        if counts["cached_input_tokens"] > counts["input_tokens"]:
            return None
        return counts

    def _credit_usage_locked(self, ev, *, final=False):
        """Apply a cumulative checkpoint delta; caller owns the Engine lock."""
        identity = self._usage_identity(ev, final=final)
        if identity is None:
            return False
        invocation_id, session_id, record = identity
        if record is not None and record.get("finalized"):
            return False
        if record is None:
            record = {"session_id": session_id, "credited_tokens": 0, "counts": None,
                      "token_status": "unavailable", "finalized": False}
            self._usage_checkpoints[invocation_id] = record
        previous = record.get("counts")
        counts = self._usage_counts(ev.get("usage"), previous)
        status = ev.get("token_status", "reported" if counts is not None else "unavailable")
        if status not in {"reported", "partial", "unavailable"}:
            status = "unavailable"
        if record.get("ambiguous"):
            status = "partial" if previous is not None else "unavailable"
        elif counts is None:
            status = "partial" if previous is not None else "unavailable"
        elif previous is not None and any(counts[key] < previous[key] for key in counts):
            record["ambiguous"] = True
            status = "partial"
        else:
            total = counts["input_tokens"] + counts["output_tokens"]
            if total < record["credited_tokens"]:
                record["ambiguous"] = True
                status = "partial"
            else:
                self.tokens += total - record["credited_tokens"]
                record["credited_tokens"] = total
                record["counts"] = counts
        record["token_status"] = status
        record["finalized"] = final
        event_source = ev.get("usage_source")
        event_source = event_source if isinstance(event_source, str) and re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", event_source) else "provider-result" if final else "provider-checkpoint"
        record["source"] = event_source
        record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._usage_source, self._usage_updated_at = record["source"], record["updated_at"]
        return True

    def _record_usage_checkpoint(self, ev):
        with self._lock:
            if not self._credit_usage_locked(ev):
                return False
            saved, warning = self._persist_usage_locked()
        self._warn_usage_persistence(warning)
        return saved

    def _record_usage_result(self, ev):
        # Also support direct callers: a duplicate final may repair durability,
        # but cannot reserve or repeat its financial accounting.
        if not self._usage_result_allowed(ev):
            return False
        attribution_warning = False
        with self._lock:
            tracked = "usage_invocation_id" in ev
            refused = tracked and self._usage_identity(ev, final=True) is None
            if refused:
                # The process still owns its error/response. Only attribution
                # failed, so retain terminal processing without invented zero
                # usage or charging another session's money and turn counts.
                self._usage_attribution_error = "usage-session-unmatched"
                self._usage_legacy_unknown = True
                attribution_warning = not self._usage_attribution_warned
                self._usage_attribution_warned = True
                self._usage_source = "unattributed-result"
                self._usage_updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                turn_tokens = None
            elif tracked:
                if not self._credit_usage_locked(ev, final=True):
                    return False
                turn_tokens = self._usage_checkpoints[_usage_uuid(ev["usage_invocation_id"])]["credited_tokens"]
            else:
                usage = ev.get("usage")
                usage = usage if isinstance(usage, dict) else {}
                # Codex cached input is a subset. Claude's separate cache
                # read/create counts retain the previous additive behavior.
                turn_tokens = sum(value for key in ("input_tokens", "output_tokens",
                    "cache_creation_input_tokens", "cache_read_input_tokens")
                    if isinstance((value := usage.get(key)), int)
                    and not isinstance(value, bool) and value >= 0)
                self.tokens += turn_tokens
                if self._usage_counts(usage) is None:
                    self._usage_legacy_unknown = True
                else:
                    self._usage_legacy_reported = True
                self._usage_source = "recorded-turn-results"
                self._usage_updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            cost = None if refused else _reported_cost(ev.get("total_cost_usd"))
            duration = (_reported_cost(ev.get("duration_ms")) or 0) / 1000
            if not refused:
                self.secs += duration
                if cost is None:
                    self.unpriced_turns += 1
                    if infer_subscription_cli(self.cli, self._usage_source) == "chatgpt":
                        counts = (self._usage_checkpoints[_usage_uuid(ev["usage_invocation_id"])].get("counts")
                                  if tracked else ev.get("usage"))
                        selection = self.model_selection if isinstance(self.model_selection, dict) else {}
                        estimate = estimate_list_price_usd(selection.get("model_served") or selection.get("model"), counts)
                        if estimate is not None:
                            self.estimated_spend += estimate
                            self.estimated_turns += 1
                else:
                    self.spend += cost
                self.turns += 1
            # Checkpoint credit and final money/turn counts are persisted as
            # one state update. A restart must not see a final reservation
            # without its financial totals, or credit a completed turn again.
            saved, warning = self._persist_usage_locked()
        self._warn_usage_persistence(warning)
        if attribution_warning:
            self._emit({"t": "sys", "text": "Usage could not be attributed to this session. The response is available, but its token and cost totals were not added."})
        return {"cost": cost, "duration": duration, "turn_tokens": turn_tokens,
                "usage_persisted": saved, "accounted": not refused}

    def _attribution_ids(self):
        """``(project_id, folder_path)`` of the registered project this effort dir
        belongs to — the ids the cockpit already uses. A hit is cached for the
        engine's life; a miss is retried (a project may be registered later)."""
        if self._project_ids is None:
            try:
                import usage_capture as _uc
                ids = _uc.resolve_project(self.dir)
            except Exception:
                ids = (None, None)
            if ids[0]:
                self._project_ids = ids
            return ids
        return self._project_ids

    def _ledger_turn(self, ev, accounting, turn_id):
        """Wave 2 S1: one write-once ledger row per finalized turn, stamped with
        the ids that flow back to the project (project_id, folder_path, this
        effort dir, the engine session, the provider's invocation id or the
        cockpit turn id). An unpriced turn keeps cost ``None``. Best-effort."""
        if (not isinstance(accounting, dict) or not accounting.get("accounted")
                or not self.session_id):
            return
        try:
            import usage_capture as _uc
            # the provider's invocation id, else cli:session:turn — no boot epoch,
            # so the same turn keys the same row across a restart (Grok R1 F6)
            native = (_usage_uuid(ev.get("usage_invocation_id"))
                      or f"{self.cli}:{self.session_id}:{self.turns}")
            project_id, folder_path = self._attribution_ids()
            served = (self.model_selection.get("model_served")
                      if isinstance(self.model_selection, dict) else None)
            usage = ev.get("usage") if isinstance(ev.get("usage"), dict) else None
            _uc.ingest_usage(
                self.session_id, _uc.turn_key(self.session_id, native),
                source=_uc.SOURCE_TERMINAL_TURN if self.general else _uc.SOURCE_STEWARD_TURN,
                native_id=native, tokens=accounting.get("turn_tokens") or 0,
                cost_usd=accounting.get("cost"), project_id=project_id,
                folder_path=folder_path, effort_dir=self.dir, cli=self.cli,
                model=served, duration_ms=int((accounting.get("duration") or 0) * 1000),
                usage=usage, provider_connection_id=self.provider_connection["id"])
        except Exception:
            pass
        self._ledger_children()

    def _spawn_env(self):
        """The steward process's environment: the model policy plus the ids its
        children inherit (project, this effort dir, where to drop receipts)."""
        import model_policy
        env = model_policy.policy_environment()
        import provider_native
        _account_env = provider_native.account_env(self.provider_connection)
        for _key in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "ANCHOR_PROVIDER_CONNECTION"):
            if _key in _account_env:
                env[_key] = _account_env[_key]
        # A1 (delegated-work PROPOSAL v0.3; Grok code R1 F1-F3, R2 N1-N2): every git ANY agent session runs - steward,
        # code job or workbench terminal - goes through gitguard, which refuses tree-rewriting verbs outside a code
        # job's own worktree BEFORE git runs: a real git.exe (found for `git` and `git.exe` alike), a `git` script and
        # BASH_ENV for Git Bash; the plain git.cmd directory only if the launcher could not be built.
        try:
            import shutil, sys as _sys
            from steward_cockpit import code_jobs as _cj
            tools_guard = str(Path(__file__).resolve().parent.parent / "tools" / "gitguard")
            try:
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location("anchor_gitguard_install", os.path.join(tools_guard, "install.py"))
                _ggi = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_ggi)
                bin_dir, bash_env = _ggi.ensure()
            except Exception:
                bin_dir, bash_env = "", ""
            guard = bin_dir or tools_guard
            path_now = env.get("PATH") or os.environ.get("PATH", "")
            skip = {os.path.normcase(p.rstrip("\\/")) for p in (bin_dir, tools_guard) if p}
            real = env.get("GITGUARD_REAL_GIT") or shutil.which("git", path=os.pathsep.join(
                p for p in path_now.split(os.pathsep) if os.path.normcase(p.rstrip("\\/")) not in skip))
            if real and os.path.isdir(guard):
                env["GITGUARD_REAL_GIT"] = real
                env["GITGUARD_PYTHON"] = _sys.executable
                env["GITGUARD_ALLOW_UNDER"] = str(_cj.jobs_base())
                env["PATH"] = guard + os.pathsep + path_now
                if bash_env:
                    env["BASH_ENV"] = bash_env
        except Exception:
            pass
        try:
            import usage_capture as _uc
            project_id, folder_path = self._attribution_ids()
            env.update(_uc.attribution_env(project_id=project_id, effort_dir=self.dir,
                                           folder_path=folder_path, session_id=self.session_id))
        except Exception:
            pass
        return env

    def _ledger_children(self, session_id=None):
        """S2: one row per child this session spawned (Codex thread children by
        root session, Claude agent transcripts), under this effort, beside the
        steward's own figure. ``session_id`` names a stored session at engine
        start (a resumed Claude steward binds its own only at its first native
        event — Grok S2 F8). Best-effort."""
        session_id = session_id or self.session_id
        if not session_id:
            return
        try:
            import usage_capture as _uc
            project_id, folder_path = self._attribution_ids()
            _uc.ingest_children(session_id, self.cli, project_id=project_id,
                                folder_path=folder_path, effort_dir=self.dir)
            _uc.ingest_receipts(parent_session=session_id, parent_effort=self.dir)
        except Exception:
            pass

    def _ack_submitted(self, proc, ev):
        """Wave 1.2 acknowledgement: a native event for this turn means the
        provider has the message; the durable copy is no longer needed.
        Under the ingress lock with a proc re-check (Grok R1 F2/F6): an old
        reader must never clear a NEWER turn's copy or touch the queue while
        say() mutates it. Returns True when it acknowledged something."""
        with self._lock:
            if proc is not self.proc or self._submitted is None:
                return False
            if ev.get("type") == "result" and ev.get("is_error") and ev.get("replay_safe") is True:
                # never submitted natively: give it back to the queue as-is
                pending = self._submitted.get("text") or ""
                if pending and pending not in self.queue:
                    self.queue.insert(0, pending)
                    self._persist_queue()
                    self._emit({"t": "sys", "text": "the turn failed before your message reached the model; it is queued again"})
            self._submitted = None
            _update_state(self.skey(), {"submitted": None})
            return True

    def _handle(self, ev, proc):
        if proc is not self.proc:
            return   # event from a superseded process - drop it entirely
        t = ev.get("type")
        if self._submitted is not None and t in ("assistant", "stream_event", "result"):
            self._ack_submitted(proc, ev)
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
        elif t == "usage_checkpoint":
            self._record_usage_checkpoint(ev)
        elif t == "stream_event":
            inner = ev.get("event", {})
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    self.last_output = time.time()
                    _tm = getattr(self, "_timing", None)
                    if _tm is not None and _tm.get("first_word") is None:
                        _tm["first_word"] = self.last_output
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
                    self._turn_tools = getattr(self, "_turn_tools", 0) + 1
                    if self._guard_turn(block):
                        return
                    inp = block.get("input") or {}
                    fp = inp.get("file_path")
                    # a Claude edit names one file_path; a Codex file_change names its paths
                    touched = [p for p in (inp.get("paths") or []) if isinstance(p, str) and p.strip()] \
                        if isinstance(inp.get("paths"), list) else []
                    if isinstance(fp, str) and fp.strip():
                        touched.insert(0, fp)
                    if block.get("name") in ("Write", "Edit", "NotebookEdit", "file_change"):
                        self._turn_wrote_files = True
                        refs = getattr(self, "_turn_output_refs", [])
                        for path in touched:
                            if path not in refs:
                                refs.append(path)
                        self._turn_output_refs = refs
                        new = [p for p in touched if p not in self.files]
                        if new:
                            self.files.extend(new)
                            _update_state(self.skey(), {"files": self.files[-40:]})
                    if getattr(self, "_timing", None) is not None:
                        self._timing["tools"] = self._timing.get("tools", 0) + 1
                    self._emit({"t": "tool",
                                "name": block.get("name", "?"),
                                "detail": _tool_detail(block),
                                "tick": self.in_tick})
        elif t == "result":
            if not self._usage_result_allowed(ev):
                return
            if proc is not self.proc:
                return   # re-check: a newer process must own this result
            # (2026-09-04, John) a model session limit is TOLD, never swallowed:
            # an error result is said in the pane with its text, a limit raises
            # the flag so the High Seat says "need you" with the reason.
            err_text = result_error_text(ev)
            if self.model_selection:
                actual = ev.get("model_served") if ev.get("model_attested") is True else None
                source = ev.get("model_source") if isinstance(ev.get("model_source"), str) else None
                if self.cli == "claude" and not err_text:
                    usage_models = ev.get("modelUsage")
                    if isinstance(usage_models, dict) and len(usage_models) == 1:
                        actual, source = next(iter(usage_models)), "cli-recorded"
                requested = self.model_selection.get("model")
                self.model_selection = {**self.model_selection, "model_served": actual,
                                        "model_attested": bool(actual),
                                        "model_source": source if actual else None}
                _update_state(self.skey(), {"model_policy": self.model_selection})
                if actual and requested and not _same_model(requested, actual):
                    self._emit({"t": "sys", "text": f"model served {actual} (requested {requested})"})
            if not err_text:
                self._journal_changed_receipt()
            if err_text:
                limit = _campaign_limit(err_text)
                self._model_limit = ("model session limit: " + err_text) if limit else ""
                self._journal_receipt("turn_error", err_text)
                hint = ev.get("stderr_hint")
                tail_text = ""
                if isinstance(hint, dict) and hint.get("kinds"):
                    tail_text = (" | native diagnostics: " + ", ".join(str(k) for k in hint["kinds"][:4])
                                 + f" ({int(hint.get('lines') or 0)} lines, content withheld)")
                self._emit({"t": "sys", "text": ("MODEL LIMIT: " if limit else
                                                 "the steward's turn ended in an error: ")
                            + err_text + tail_text})
                if limit:
                    try:
                        from steward_cockpit import steward_campaign as campaign
                        campaign.write_attention(
                            self.dir, "needs_you", self._model_limit,
                            failure_code="MODEL_LIMIT")
                    except Exception:
                        pass
            accounting = self._record_usage_result(ev)
            if not accounting:
                return
            cost, duration, turn_tokens = accounting["cost"], accounting["duration"], accounting["turn_tokens"]
            # pinned open question: scan the WHOLE final text for the last
            # question-bearing sentence (not just a trailing "?"), so a
            # question mid-paragraph still pins. Tick turns never pin.
            txt = self.turn_text.strip()

            was_tick = self.in_tick
            completed_turn_id = f"{self.cli}:{self.session_id}:{self.epoch}:{self.turns}"
            self._ledger_turn(ev, accounting, completed_turn_id)
            producer_id = getattr(self, "_refinement_producer_id", None)
            # the goal's tag rides THIS turn: read from the text that went to stdin for it (Grok W2: never a slot
            # set at say(), which the next unrelated turn could wear)
            _goal_tag = None if (was_tick or getattr(self, "_turn_origin", "") != "human") else _goal_in(getattr(self, "_last_submitted", ""))
            history_saved = (not txt or was_tick or self._record_conversation(
                "steward", txt, turn_id=completed_turn_id, goal=_goal_tag))
            if (producer_id and getattr(self, "_turn_wrote_files", False) and not was_tick
                    and (Path(self.dir) / "roadmap.json").is_file()):
                payload = {
                    "producer_kind": "conversation", "producer_id": producer_id,
                    "source_ref": "Cockpit conversation " + completed_turn_id,
                    "context": getattr(self, "_refinement_dispatch_context", None),
                    "outputs": list(getattr(self, "_turn_output_refs", [])),
                    "inventory_complete": False,
                    "terminal": "failed" if err_text else "done",
                }
                with self._refinement_pending_lock:
                    self._pending_refinement_handoffs[producer_id] = payload
                    saved = _update_state(self.skey(), {
                        "pending_refinement_handoffs": self._pending_refinement_handoffs})
                if not saved:
                    self._emit({"t": "sys", "text": "Refinement handoff persistence needs repair; automatic continuation is held."})
            self._retry_refinement_handoffs()

            # The complete result boundary is one arbitration transaction.
            # Exactly one next writer wins: an already accepted human message,
            # one machine nudge, auto-drive, or idle. Status I/O happens only
            # after this decision, so it cannot open an overtaking window.
            with self._lock:
                if proc is not self.proc:
                    return
                pinned_now = False
                question_attention = self._attention()
                if question_attention.get("managed_refinement"):
                    self.open_question = ""
                    self.open_question_kind = ""
                if not was_tick:
                    sentences = [s.strip() for s in
                                 re.split(r"(?<=[.!?])\s+|\n+", txt)      # a line break ends a line such as "Reversible: no"
                                 if s.strip().endswith("?")]
                    if sentences and (not question_attention.get("managed_refinement") or
                            question_attention.get("pending_request") or _has_recommendation(txt)):
                        request = question_attention.get("pending_request") or {}
                        step_id = request.get("step_id") or self._read_strip().get("current_step_id")
                        prior = self.question_context if isinstance(self.question_context, dict) else None
                        answered = self._answered_before(sentences[-1], step_id)
                        if answered:
                            # answered means retired: never pinned again; the steward is told once
                            if not answered.get("reask_told_at"):
                                answered["reask_told_at"] = time.time()
                                _update_state(self.skey(), {"question_history": self.question_history})
                                self._reasked_answered = answered
                        else:
                            self.open_question = sentences[-1]
                            self.open_question_kind = _question_kind(
                                self.open_question)
                            # the reshape re-ask keeps the decision's identity; a changed
                            # question while one is open names what it replaces
                            origin_id = prior.get("id") if (prior and self._decision_nudged) else None
                            replaced = (prior if (prior and not origin_id and prior.get("question") != self.open_question
                                        and (prior.get("authorization_scope") or {}).get("step_id") == step_id) else None)
                            self.question_context = save_question_context(self.open_question, txt,
                                asked_at=time.time(), source_ref="Cockpit conversation",
                                scope={"request_id":request.get("id"), "step_id":step_id,
                                       "presentation_id":request.get("presentation_id"),
                                       "source_turn_id":completed_turn_id,
                                       "work_digest":question_attention.get("work_digest")},
                                origin_id=origin_id,
                                what_changed=replaced.get("question") if replaced else None)
                            pinned_now = True

                _update_state(self.skey(), {
                    # The outcome is the conclusion, not the opening of a long
                    # reply. Pickup already applies its own display bound.
                    "last_text": txt[-240:],
                    "last_used": time.strftime("%Y-%m-%d %H:%M"),
                    "cli": self.cli,
                    "open_question": self.open_question,
                    "open_question_kind": self.open_question_kind,
                    "question_context": self.question_context,
                    "epoch": self.epoch,
                })
                self.busy = False
                self._record_timing(duration, was_tick)
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
                            selection = _cap_effort(selection, None if self.general else STEWARD_CONVERSATION_EFFORT)
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
                    self._deliver_next_queued_locked()
                elif (self._human_asked and not txt and not was_tick
                      and not self._answer_nudged and not self.general):
                    self._answer_nudged = True
                    self._human_asked = False
                    self._send_locked(
                        "(interface - not John) You ended without answering "
                        "John in words. Reply now in one or two plain "
                        "sentences.")
                elif (getattr(self, "_reasked_answered", None) and not was_tick
                      and not self.general):
                    entry = self._reasked_answered
                    self._reasked_answered = None
                    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.get("answered_at") or 0))
                    self._send_locked(
                        "(interface - not John) John already answered this question at " + when
                        + ": \"" + str(entry.get("answer") or "")[:300]
                        + "\". Do not ask it again; act on his answer.")
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
                        "line of why, then the realistic alternatives as bullet "
                        "lines, a phrase each with the trade-off, then the "
                        "question as the LAST line, answerable in one word.")
                else:
                    if txt:
                        self._human_asked = False
                    self._maybe_drive_locked(was_tick, txt)
                # R3 (Grok code F4): a code job's coder is finished when its turn ended and nothing follows it (a
                # failover that keeps working returned above; a queued or driven turn keeps it busy)
                if self.on_turn_done is not None and not self.busy and not self.queue:
                    self._fire_turn_done({"text": txt, "error": err_text or ""})

            # Publish the post-arbitration truth (including a just-started
            # queued/nudge/drive turn) without holding the stdin arbiter lock.
            self._status_update(emit=True)

    # ---------- proactive drive ----------
    DRIVE_CAP = 50

    def _maybe_drive(self, was_tick=False):
        """Compatibility wrapper for tests/callers outside turn arbitration."""
        with self._lock:
            return self._maybe_drive_locked(was_tick, self.turn_text.strip())

    def _retry_refinement_handoffs(self):
        """Drain one saved observation through the existing ledger, never under the stdin lock."""
        if not getattr(self, "_pending_refinement_handoffs", {}):
            return True
        if not self._refinement_retry_lock.acquire(blocking=False):
            return False
        try:
            with self._refinement_pending_lock:
                if not self._pending_refinement_handoffs:
                    return True
                producer_id, payload = next(iter(self._pending_refinement_handoffs.items()))
                # A failed session-state write must not silently orphan an observation.
                if not _update_state(self.skey(), {
                        "pending_refinement_handoffs": self._pending_refinement_handoffs}):
                    return False
            from steward_cockpit.producer_handoff import record_handoff
            try:
                receipt = record_handoff(self.dir, **payload)
            except Exception as exc:
                receipt = {"ok": False, "error": "handoff-recording-failed",
                           "detail": type(exc).__name__}
            with self._refinement_pending_lock:
                remaining = dict(self._pending_refinement_handoffs)
                if receipt.get("ok"):
                    remaining.pop(producer_id, None)
                acknowledged = _update_state(self.skey(), {
                    "pending_refinement_handoffs": remaining,
                    "refinement_handoff": receipt})
                if acknowledged:
                    self._pending_refinement_handoffs = remaining
            error = (receipt.get("error") if not receipt.get("ok") else
                     "handoff-receipt-persistence-failed" if not acknowledged else None)
            if error and error != self._refinement_handoff_error:
                self._emit({"t": "sys", "text": "Work completed, but its refinement handoff needs repair: " + str(error)})
            self._refinement_handoff_error = error
            return bool(receipt.get("ok") and acknowledged)
        finally:
            self._refinement_retry_lock.release()

    def _maybe_drive_locked(self, was_tick=False, completed_text=""):
        """Choose and send one drive continuation while holding ``_lock``.

        Human ingress, queued text, nudges, and drive all share this arbiter;
        drive must never stack onto an already accepted turn.
        """
        if (self.busy or self.queue or not self.drive or not self.alive()
                or getattr(self, "_pending_refinement_handoffs", {})):
            return
        from steward_cockpit import maintenance
        if maintenance.is_active():
            return  # Wave 1.6: no self-started turn behind the barrier
        if was_tick:
            return   # a cadence-tick turn is not a step - never counts as drive
        txt = (completed_text or "").strip()
        try:
            from steward_cockpit import steward_campaign as campaign
            attention = campaign.read_map(self.dir)["attention"]
        except Exception:
            attention = {"state": "unknown"}
        if attention.get("managed_refinement"):
            if (self._question_contexts(attention) or attention.get("producer_recovery_required")
                    or attention.get("state") == "unknown"):
                return
        elif self.open_question or txt.endswith("?"):
            return
        att = attention.get("state")
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

    def _record_timing(self, duration, was_tick):
        """W1 of the two-lane plan (2026-10-05): one line per turn in <effort>/.ecgberht/turn-timing.jsonl - how long his
        message waited, how long to the first word, the whole turn, the tools. Never raises; the measurement never costs
        a turn."""
        tm = getattr(self, "_timing", None) or {}
        self._timing = None
        try:
            started = float(tm.get("started") or 0)
            if not started:
                return
            row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "origin": "tick" if was_tick else getattr(self, "_turn_origin", ""),
                   "cli": self.cli, "effort": (self.model_selection or {}).get("effort"),
                   "queued_s": round(started - tm["arrived"], 1) if tm.get("arrived") else None,
                   "first_word_s": round(tm["first_word"] - started, 1) if tm.get("first_word") else None,
                   "turn_s": round(float(duration or 0), 1), "tools": int(tm.get("tools") or 0)}
            p = Path(self.dir) / ".ecgberht" / "turn-timing.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass

    def _working_bg(self):
        """True when the campaign flag says commissioned/background work is
        in flight — disk truth, zero-model. The steward's own turn may be
        idle while a commissioned run (Gandalf, Foreman) works; the old
        busy-only cadence showed NOTHING for exactly the long work John
        wants to watch (handoff 2026-08-25 #2a)."""
        if self._attention().get("state") == "working":
            return True
        try:   # 2026-10-05: a running code job is background work the cadence must narrate
            from steward_cockpit.steward_campaign import running_code_jobs
            return bool(running_code_jobs(self.dir))
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

    def _idle_tick(self, now):
        """Automatic sleep: quiet (no talk, no work, nothing queued) for
        IDLE_SLEEP_SECONDS -> park the process; resume is seamless. A
        commissioned/background run COUNTS AS WORK: the engine stays awake so
        the 10-minute status keeps flowing while it runs. The Campaign's own
        steward (W5, 2026-10-01: one conversation) takes the same checkpoint
        once per quiet spell and stays awake. True = parked."""
        quiet_since = max(self.last_say, self.last_output, self.woke_at)
        if (self.busy or self.queue or now - quiet_since <= IDLE_SLEEP_SECONDS
                or self._working_bg()):
            return False
        if self.one_conversation and self._idle_marked == quiet_since:
            return False
        # commit-on-idle-close is a real mechanism, not a prompt
        self._commit_if_dirty("steward idle checkpoint" if self.one_conversation
                              else "steward auto-sleep checkpoint")
        if self.one_conversation:
            # it stays up: no leave receipt against an open conversation (Grok
            # W5) - the explicit project switch remains the leave
            self._idle_marked = quiet_since
            return False
        # W0 of the steward revision (2026-09-28): the FALLBACK leave receipt — only when
        # presence still says he is on this project (he never switched away); the explicit
        # switch on the High Seat or another cockpit is the trigger, this is the safety net.
        try:
            from . import presence as _pres
            _pres.leave_if_still_here(
                self.dir, lambda _pid, at: _pres.run_leave(self.dir, at))
        except Exception:
            pass
        self._emit({"t": "sys", "text":
                    f"steward asleep after {IDLE_SLEEP_SECONDS // 60} "
                    "quiet minutes - everything saved; your next message wakes it"})
        self.stop()
        return True

    def _ticker(self, proc):
        while proc is self.proc and proc.poll() is None:
            time.sleep(TICK_CHECK)
            if proc is not self.proc:   # superseded by a newer process
                return
            now = time.time()
            if not self.busy and self._pending_refinement_handoffs:
                if self._retry_refinement_handoffs():
                    with self._lock:
                        self._maybe_drive_locked()
            if self._idle_tick(now):
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
                # Wave 1.2: nothing is written into a busy broker any more.
                # Every TICK/REASSERT envelope queued in the pipe became an
                # extra full turn after the running one (Codex r2 F2) and
                # delayed John's next message again. The cadence commit below
                # still keys off last_tick; the role re-assert moves to the
                # resume prefix (Wave 2.1).
                self.last_tick = now
            # commit-as-you-go IS a mechanism now: a dirty tree gets committed
            # on the cadence, independent of whether the model remembers
            if now - self.last_tick < 2:
                self._commit_if_dirty("steward cadence checkpoint")

    def _commit_if_dirty(self, message):
        """The campaign's own paths only; other staging untouched; announced only on git's word. Takes the
        repository's one commit lock (git_safety, Grok R2 G1) so it never lands inside a code job's land."""
        try:
            import git_safety as _gs
            _lock = _gs.repo_lock(_gs.toplevel(self.dir) or self.dir, wait_s=30, who="steward commit " + str(self.dir))
        except Exception:
            return None      # never commit without the lock (Grok code R1 F7)
        with _lock as held:
            if not held:
                return None      # a land holds the lock: the next cadence tick commits
            return self._commit_if_dirty_locked(message)

    def _checkpoint_paths(self):
        """What a steward checkpoint may commit: its own subtree when the cockpit is a folder inside a repository; only
        the steward's bookkeeping when the cockpit folder IS the repository root (e.g. the Anchor project's cockpit at
        C:\\dev\\Anchor), so a checkpoint never sweeps other sessions' files (Grok code R1 F8)."""
        try:
            import git_safety as _gs
            root = _gs.toplevel(self.dir)
        except Exception:
            root = ""
        if root and root != os.path.normcase(str(Path(self.dir).resolve())):
            return ["."]
        keep = ["ECGBERHT.md", "roadmap.json", "strip.json", "DELIVERABLES.md", "journal", ".ecgberht"]
        return [k for k in keep if (Path(self.dir) / k).exists()] or ["ECGBERHT.md"]

    def _commit_if_dirty_locked(self, message):
        if self.fake:
            return
        try:
            dirty = subprocess.run(
                ["git", "status", "--porcelain", "--", *self._checkpoint_paths()], cwd=self.dir,
                capture_output=True, text=True, timeout=15)
            if dirty.returncode != 0 or not dirty.stdout.strip():
                return
            add = subprocess.run(["git", "add", "-A", "--", *self._checkpoint_paths()], cwd=self.dir,
                                 capture_output=True, text=True, timeout=30)
            commit = (subprocess.run(["git", "commit", "-m", message, "--", *self._checkpoint_paths()], cwd=self.dir,
                                     capture_output=True, text=True, timeout=30)
                      if add.returncode == 0 else add)
            if commit.returncode == 0:
                # cadence housekeeping → the status pane, not the conversation
                self._emit({"t": "sys", "tick": True,
                            "text": "committed work-in-progress (cadence)"})
            else:
                tail = (commit.stderr or commit.stdout or "").strip().splitlines()
                self._emit({"t": "sys", "tick": True,
                            "text": "commit failed: " + (tail[-1] if tail else f"git exit {commit.returncode}")})
        except Exception as exc:
            self._emit({"t": "sys", "tick": True, "text": "commit failed: " + str(exc)})

    # ---------- journal receipts ----------
    def _journal_receipt(self, kind, detail):
        """An engine-detected event (turn error, interrupt, stop, rollover) as a
        journal_update receipt on strip.json, so the Journal row is never blank
        for something the engine saw. Best-effort."""
        try:
            text = str(detail or "").strip().replace("\r", " ").replace("\n", " ")[:300]
            stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            self._strip_receipt({"kind": "journal_update", "entry_id": f"engine-{stamp}-{kind}",
                                 "summary": f"{kind}: {text}"})
        except Exception:
            pass

    def _journal_changed_receipt(self):
        """At turn end: the steward's newest journal entry gets one receipt
        (the strip's last journal receipt says whether it already has one)."""
        try:
            base = Path(self.dir)
            newest, newest_m = None, 0.0
            for rel in ("journal", ".ecgberht/journal"):
                d = base / rel
                if d.is_dir():
                    for p in d.glob("*.md"):
                        m = p.stat().st_mtime
                        if m > newest_m:
                            newest, newest_m = p, m
            if newest is None:
                return
            if any(isinstance(r, dict) and r.get("entry_id") == newest.stem
                   for r in self._read_strip().get("receipts") or []):
                return                                   # already receipted
            first = ""
            with io.open(newest, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.strip():
                        first = line.strip().lstrip("# ").strip()
                        break
            self._strip_receipt({"kind": "journal_update", "path": newest.relative_to(base).as_posix(),
                                 "entry_id": newest.stem, "summary": first[:300] or newest.stem})
        except Exception:
            pass

    def proceed_on_silence(self, question_id, now=None):
        """A reversible decision with an undo and a recommendation proceeds on that recommendation
        after SILENCE_SECONDS of John's silence: the steward is told first (a failed tell is retried
        by the next tick), then the decision is recorded as proceeded on silence - never as his
        words - and the wait on him cleared. A review request (the ledger's) never proceeds so."""
        now = time.time() if now is None else now
        with self._lock:
            q = next((c for c in self._question_contexts(self._attention()) if c.get("id") == question_id), None)
            if not q or q.get("reversible") is not True or not q.get("undo") or not q.get("recommendation"):
                return {"ok": False, "reason": "not a reversible decision with an undo and a recommendation"}
            if (q.get("authorization_scope") or {}).get("request_id"):
                return {"ok": False, "reason": "a review request waits for John"}
            asked = q.get("asked_at")
            if not isinstance(asked, (int, float)) or isinstance(asked, bool) or now - asked < SILENCE_SECONDS:
                return {"ok": False, "reason": "not yet"}
            if any((e.get("question") or {}).get("id") == question_id for e in self.question_history):
                return {"ok": False, "reason": "already decided"}
        line = ("Proceeded on silence: John did not answer within %d hours and the decision was reversible, "
                "so the recommendation stands - %s Undo: %s") % (SILENCE_SECONDS // 3600, q["recommendation"], q["undo"])
        told = self.say(line, human=False)
        if not told.get("ok"):
            return {"ok": False, "reason": told.get("error") or "the steward could not be told"}
        with self._lock:
            entry = {"question": q, "answer": q["recommendation"], "answered_at": now,
                     "status": "proceeded_on_silence", "source_ref": "silence"}
            history = (list(self.question_history) + [entry])[-100:]
            if not _update_state(self.skey(), {"question_history": history, "open_question": "",
                                               "open_question_kind": "", "question_context": None}):
                return {"ok": False, "reason": "state not saved"}
            self.question_history = history
            self.open_question, self.open_question_kind, self.question_context = "", "", None
            self._answer_nudged = self._decision_nudged = False
            self._strip_clear_wait()
        return {"ok": True, "reason": ""}

    def _answered_before(self, question, step_id):
        """The history entry that already answered this very question on this
        step, else None."""
        for entry in reversed(getattr(self, "question_history", None) or []):
            saved = entry.get("question") if isinstance(entry, dict) else None
            if isinstance(saved, dict) and str(saved.get("question") or "").strip() == str(question or "").strip() \
                    and (saved.get("authorization_scope") or {}).get("step_id") == step_id:
                return entry
        return None

    def _strip_clear_wait(self):
        """John answered a decision: the wait on him is over. The engine's one
        strip field, one atomic write under the process lock, never minting a
        strip that does not exist (a product review's wait is the ledger's)."""
        path = Path(self.dir) / "strip.json"
        with _paths.WRITE_LOCK:
            if not path.is_file():
                return
            strip = self._read_strip()
            if not strip or not str(strip.get("human_wait") or "").strip():
                return
            strip["human_wait"] = ""
            tmp = path.with_suffix(".json.engine.tmp")
            tmp.write_text(json.dumps(strip, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)

    def _read_strip(self):
        path = Path(self.dir) / "strip.json"
        try:
            strip = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            strip = {}
        return strip if isinstance(strip, dict) else {}

    def _strip_receipt(self, receipt):
        """Append one receipt to the campaign's strip.json (bounded to 60). The
        strip has one writer (the steward); the engine re-reads it at the moment
        of writing under the process lock and touches only ``receipts``, and
        never mints a strip that does not exist."""
        path = Path(self.dir) / "strip.json"
        with _paths.WRITE_LOCK:
            if not path.is_file():
                return
            strip = self._read_strip()
            if not strip:
                return
            receipts = strip.get("receipts") if isinstance(strip.get("receipts"), list) else []
            receipts.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "engine",
                             "step_id": strip.get("current_step_id"), "session_id": self.session_id, **receipt})
            strip["receipts"] = receipts[-60:]
            tmp = path.with_suffix(".json.engine.tmp")
            tmp.write_text(json.dumps(strip, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)


#: The recommendation matcher lives in question_context (ONE matcher for the
#: decision-shape check and the saved record); ``_has_recommendation`` is it.


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


_SNAPSHOT_SUFFIX = re.compile(r"^-(?:\d[\d-]*|build.*)$")


def _same_model(requested, served):
    """The served id is the requested one, or the requested one plus a dated
    snapshot (``-2026-09-01``) or build suffix (``-build``); a sibling
    (``gpt-6-astra-mini``, ``gpt-5.4`` for ``gpt-5``) is a different model."""
    requested, served = str(requested or ""), str(served or "")
    if not requested or not served:
        return True
    if served == requested:
        return True
    return served.startswith(requested) and bool(_SNAPSHOT_SUFFIX.match(served[len(requested):]))


def _tool_detail(block):
    inp = block.get("input") or {}
    name = block.get("name", "")
    for key in ("skill", "command", "description", "file_path", "prompt",
                "pattern", "query"):
        if key in inp and isinstance(inp[key], str):
            text = inp[key].replace("\n", " ")
            return text[:90] + ("..." if len(text) > 90 else "")
    if isinstance(inp.get("paths"), list) and inp["paths"]:
        text = ", ".join(str(p) for p in inp["paths"][:6])
        return text[:90] + ("..." if len(text) > 90 else "")
    return ""
