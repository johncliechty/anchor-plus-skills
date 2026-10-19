"""Session-owned synthetic live proof; not part of any release archive."""
import json
import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import anchor_settings
import model_policy
from steward_cockpit.codex_turn_bridge import Broker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=('chatgpt', 'grok'), default='chatgpt')
    args = parser.parse_args()
    tag = 'codex' if args.provider == 'chatgpt' else 'grok'
    bridge_type = Broker
    if args.provider == 'grok':
        from steward_cockpit.grok_turn_bridge import GrokBroker
        bridge_type = GrokBroker
    directory = Path(__file__).resolve().parent
    receipt_file = directory / (tag + "-cockpit-proof.json")
    if receipt_file.exists():
        raise RuntimeError("Proof receipt already exists; refuse overwrite")
    target = directory / ("live-" + tag + "-synthetic")
    target.mkdir(exist_ok=False)
    selection = model_policy.resolve(args.provider, settings=anchor_settings.get_launch_settings())
    receipt = {"started": time.time(), "status": "running", "selection": selection,
               "target": target.name, "turns": [], "events": []}
    def save():
        receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    def emit(event):
        receipt["events"].append(event)
        save()
        print(json.dumps({"event": event.get("type"), "subtype": event.get("subtype"),
                          "session_id": event.get("session_id"), "is_error": event.get("is_error")}), flush=True)
    save()
    broker = bridge_type(target=str(target), model=selection["model"], effort=selection["effort"],
                    permission_mode="plan", emit=emit, turn_timeout_seconds=300)
    try:
        for text in (
            "This is a synthetic transport test. Do not use tools, delegate, or change any files. Remember the phrase BLUE-PINE-17 for my next message. Reply only: remembered.",
            "What exact phrase did I ask you to remember? Reply with the phrase only. Do not use tools or change files.",
        ):
            result = broker.turn({"type": "user", "message": {"content": [{"type": "text", "text": text}]}})
            receipt["turns"].append(result)
            save()
            if result.get("is_error"):
                receipt["status"] = "failed"
                return 2
        turns = receipt["turns"]
        receipt["same_native_thread"] = bool(turns[0].get("session_id") and turns[0]["session_id"] == turns[1].get("session_id"))
        receipt["memory_preserved"] = "BLUE-PINE-17" in turns[1].get("result", "")
        receipt["descendants_verified"] = all(turn.get("containment", {}).get("descendants_verified") for turn in turns)
        receipt["status"] = "passed" if all(receipt[key] for key in ("same_native_thread", "memory_preserved", "descendants_verified")) else "failed"
        return 0 if receipt["status"] == "passed" else 2
    finally:
        broker.stop()
        receipt["finished"] = time.time()
        save()
        print(json.dumps({key: receipt.get(key) for key in ("status", "same_native_thread", "memory_preserved", "descendants_verified")}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
