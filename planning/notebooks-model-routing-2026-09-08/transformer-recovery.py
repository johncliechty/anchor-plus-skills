"""Session-owned, exact-source Transformer recovery; never emits credentials."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("recovery_live", Path(__file__).with_name("recovery-live.py"))
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
PROJECT = "bd8f0e938fb24af5b689ba830c902bff"
EFFORT = "Hierarchical AR Networks"
CAMPAIGN = Path(r"C:\dev\Mathematics Problems\Transformer Math\Hierarchical AR Networks")
SESSION = "91e0e924-0ba6-40e2-b4f3-2d5ceac01545"
SOURCE = Path(r"C:\Users\john\.claude\projects\C--dev-Mathematics-Problems-Transformer-Math-Hierarchical-AR-Networks") / (SESSION + ".jsonl")
RECEIPT = Path(__file__).with_name("transformer-restoration-receipt.json")
QUERY = "?pid=" + PROJECT + "&dir=" + quote(EFFORT)


def inspect():
    value = live.request("/api/steward/state" + QUERY)
    print(json.dumps({"state": {key: value.get(key) for key in (
        "alive", "busy", "cli", "selected_cli", "session_id", "pending_switch",
        "model_policy", "queued", "history_error", "error", "pending_queue")}}))
    return value


def recover():
    state = inspect()
    if state.get("busy") or state.get("alive"):
        raise RuntimeError("Recovery requires the selected old engine to be parked")
    saved = json.loads((ROOT / "steward-cockpit-state.json").read_text(encoding="utf-8"))[str(CAMPAIGN)]
    if saved.get("session_id") != SESSION or saved.get("cli") != "claude":
        raise RuntimeError("Saved native identity changed; no import attempted")
    original = SOURCE.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    from steward_cockpit import steward_engine as engine
    exclusions = [engine.STAND_UP, engine.STAND_UP_NEW, engine.RESUME_BRIEF, engine.REASSERT, engine.TICK]
    # These reserved engine/interface records were identified in this exact
    # transcript. Store their whole text as exact exclusions, not a substring
    # rule that could erase John's quotations or commands.
    prefixes = (
        "(engine resume - not John) You are Ecgberht,",
        "(interface - not John) You ended without answering John",
        "(interface - not John) You put a decision to John without a recommendation",
    )
    for line in original.decode("utf-8-sig").split("\n"):
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") != "user":
            continue
        content = item.get("message", {}).get("content", [])
        blocks = [content] if isinstance(content, str) else [b["text"] for b in content if b.get("type") == "text"]
        joined = "\n".join(blocks)
        if joined.startswith(prefixes):
            exclusions.append(joined)
    from steward_cockpit.legacy_claude_history import import_legacy_claude
    result = import_legacy_claude(CAMPAIGN, SESSION, excluded_prompts=exclusions)
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != before:
        raise RuntimeError("Native source hash changed during recovery; inspect before any pickup")
    history = json.loads((CAMPAIGN / ".ecgberht" / "conversation-log.json").read_text(encoding="utf-8"))
    turns = history if isinstance(history, list) else history.get("turns", [])
    required = ["What are you looking for wrt getting approvals", "You should be using ChatGPT and Grok now, not fabel"]
    if not all(any(t.get("role") == "john" and t.get("text") == value for t in turns) for value in required):
        raise RuntimeError("Recovered history did not verify both original morning submissions")
    print(json.dumps({"recovery": result, "original_sha256": before,
        "original_unchanged": True, "morning_messages_verified": 2, "canonical_turns": len(turns)}))


def submit():
    if RECEIPT.exists():
        raise RuntimeError("Handoff receipt already exists; no automatic replay")
    if not (CAMPAIGN / ".ecgberht" / "conversation-log.json").is_file():
        raise RuntimeError("Canonical recovery required before pickup")
    message = (
        "MAINTENANCE HANDOFF — not a newly dictated project requirement. John asked Anchor maintenance today to recover his submitted Transformer Math instructions and get this existing project going with ChatGPT and Grok. "
        "The original Claude transcript remains untouched. Its complete eligible conversation text, including his actual September 8 morning submissions, is now restored verbatim with source IDs in .ecgberht/conversation-log.json. Read that full record and the existing Face, roadmap, Strip, deliverables, plans and latest journal before acting; do not invent missing materials or ask John to dictate them again. "
        "His morning question was: 'What are you looking for wrt getting approvals'. His next instruction was: 'You should be using ChatGPT and Grok now, not fabel'. Earlier actual instructions include 'Okay, we can move on.' and 'Yes please move forward with the next steps.' "
        "His CURRENT request authorizes recovery and resumption of already-authorized work. Preserve that authorization across this provider pickup, per the September 8 user-global rule. Do not create another approval gate merely because a session restarted, and do not replay completed or ambiguously executed actions. Reconcile the recovered instructions against existing receipts, explain briefly any genuinely unresolved decision, and continue safe already-authorized next steps. Optional later material is not a reason to stop independent work. "
        "Use current Anchor settings for the actual coding/review seats (ChatGPT/Grok), discover the latest supported models and highest supported effort, and stamp actual served identity honestly. Do not silently use Claude or invent cross-family verification. Keep feedback brief and meaningful, with the standard scheduled status in the status pane. First confirm that you can read the restored conversation and existing project materials."
    )
    with RECEIPT.open("x", encoding="utf-8") as handle:
        json.dump({"status": "submission_pending", "source_session": SESSION, "handoff_sha256": hashlib.sha256(message.encode()).hexdigest()}, handle)
    result = live.request("/api/steward/say", {"pid": PROJECT, "dir": EFFORT, "text": message})
    RECEIPT.write_text(json.dumps({"status": "accepted" if result.get("ok") else "not_accepted",
        "source_session": SESSION, "result": result}, indent=2), encoding="utf-8")
    print(json.dumps({"handoff": result}))


def events():
    result = live.request("/api/steward/events" + QUERY + "&since=0")
    state = result.get("state", {})
    print(json.dumps({"state": {key: state.get(key) for key in (
        "alive", "busy", "cli", "selected_cli", "session_id", "model_policy", "queued", "history_error")},
        "events": [{k: e.get(k) for k in ("t", "id", "kind", "type", "failure_code", "turn_limits", "duration_ms") if k in e}
            for e in result.get("events", [])[-6:]],
        "feedback": [e.get("text", "")[:1200] for e in result.get("events", [])
            if e.get("t") in ("steward", "sys")][-3:]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect", "recover", "submit", "events"))
    args = parser.parse_args()
    {"inspect": inspect, "recover": recover, "submit": submit, "events": events}[args.action]()
