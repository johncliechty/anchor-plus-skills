"""Capture John's exact feedback through Anchor's existing friction writer."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import friction_journal

WORDS = "Great, then why is the health banner warning still shwoing on the Cave of Wonders (that should not be the case--can you please analyzie why this did not get cleaned up and then journal about it wrt Anchor)."


def main():
    title = "Cave retains resolved Doctor health banner; completion missed existing client"
    matches = [r for r in friction_journal.list_records()
               if r.get("title") == title and r.get("body") == WORDS]
    if matches:
        record = matches[0]
    else:
        record = friction_journal.capture(
            title, body=WORDS, severity="friction", source="user", route="/",
            engine="chatgpt", extra_context={
                "analysis_document": "docs/friction/2026-10-07-cave-health-banner-cleanup.md",
                "journal_document": "journal/2026-10-07-cave-health-banner-cleanup.md",
                "latest_report": "health_reports/2026-10-07.md",
                "live_evidence": "docs/friction/2026-10-07-cave-health/live-evidence.json",
                "browser_receipt": "docs/friction/2026-10-07-cave-health/browser-receipt.json",
                "fresh_banner_count": 0,
                "stale_banner_count_after_refresh": 1,
                "correctness_issues": 0,
                "native_wake_and_write_guard": True,
                "existing_client_inspected": False,
                "production_banner_implementation_changed": False,
            })
    readback = friction_journal.load(record["id"])
    assert readback and readback["body"] == WORDS and readback["status"] == "open"
    assert any(r["id"] == record["id"] for r in friction_journal.list_records(status="open"))
    brief = friction_journal.friction_report()
    assert record["id"] in brief and title in brief
    receipt = {"canonical_record": "friction/" + record["id"] + ".json",
               "status": readback["status"], "verbatim_words_verified": True,
               "open_intake_inclusion_verified": True}
    (Path(__file__).parent / "journal-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
