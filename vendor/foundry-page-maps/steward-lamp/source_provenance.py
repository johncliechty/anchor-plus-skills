"""Lamp source policy: current code, explicitly frozen historical examples.

The shared validator still compares every origin and snapshot hash. Only the
named example records below use their delivered snapshot as the origin; code,
instructions and other skill guides always retain their authoritative origin.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "shared"))
from validate_display import contained, validate as validate_display
from render_display import render, esc

CAMPAIGN = Path("C:/dev/Skill Foundry/Foundry page and knowledge maps")
ECG = Path("C:/dev/Ecgberht")
EXAMPLES = {
    "effort-face": (CAMPAIGN / "ECGBERHT.md", "use record", "Narrative at capture; later stewardship can change the active effort. This is not current campaign state."),
    "effort-strip": (CAMPAIGN / "strip.json", "use record", "Heartbeat and append-only receipts at capture; later instruments can advance. This is not live activity proof."),
    "effort-roadmap": (CAMPAIGN / "roadmap.json", "use record", "Events and projection at capture; later events can change order and progress. This is not the current roadmap."),
    "dialogue": (CAMPAIGN / ".ecgberht/conversation-log.json", "frozen dialogue", "Frozen full dialogue through the last captured turn, preserving original authority and corrections; later turns are outside this example."),
    "plan-receipt": (CAMPAIGN / "planning/working-plan/review-1-receipt.json", "use record", "Named PDF review-copy-1 receipt at capture; current PDF identity and reader checks are separately verified by check_handoff.py."),
    "foundry-handoff": (CAMPAIGN / "journal/0005-researchprime-refinement-1-handback.md", "use record", "Historical researchPrime handback; its reported outcome does not establish current deployment or acceptance."),
    "slow-first": (ECG / "journal/2069-cave-dialogue-slow-turns.md", "use record", "Historical Cave diagnosis, later corrected by entry 2070; not a measured Lamp run."),
    "slow-corrected": (ECG / "journal/2070-cave-slowness-is-ceremony-and-throughput.md", "use record", "Historical corrected Cave diagnosis; not a current performance benchmark."),
    "responsive": (ECG / "journal/2071-steward-responsiveness-live.md", "use record", "Historical shipped-change entry with no measured faster reply yet; not today's runtime proof."),
    "landing-failed": (ECG / "journal/2072-landing-rollback-incident.md", "use record", "Historical shared-tree rollback incident; not a reproduction of current landing behavior."),
    "landing-fixed": (ECG / "journal/2073-safe-landing-live.md", "use record", "Historical repair report; current code is anchored separately and live landing is not reproduced here."),
    "sleep-example": (ECG / "journal/0076-sleep-cycle-promoted-a-gandalf-lesson-into-a-live-bug.md", "use record", "Historical cross-skill lesson and reported CLI fix; does not authorize a new construction wave."),
    "usage-run": (ECG / "journal/runs/2026-09-10T20-33-23Z-steward-project-usage.json", "run receipt", "Historical usage-repair receipt; reported review, service and activation apply only to that run. Native receipts were not inspected here."),
    "plan-run": (CAMPAIGN / "journal/runs/2026-10-05-foundry-plan-pdf-review.json", "run receipt", "Named plan-review run at capture; not exhaustive capture coverage or resource-access frequency."),
}


def validate(data, root, repo):
    errors = validate_display(data, root, repo)
    root, repo = Path(root).resolve(), Path(repo).resolve()
    for s in data.get("sources", []):
        sid = s.get("id")
        try:
            captured = datetime.fromisoformat(s.get("captured_at", ""))
            assert captured.tzinfo is not None and captured <= datetime.now(timezone.utc)
        except (ValueError, TypeError, AssertionError):
            errors.append("missing valid capture time " + str(sid))
        snapshot = contained(root, s.get("snapshot"))
        origin = Path(s.get("origin", ""))
        origin = origin if origin.is_absolute() else repo / origin
        if sid in EXAMPLES:
            original, kind, applicability = EXAMPLES[sid]
            if (s.get("freshness") != "frozen-example" or s.get("kind") != kind
                    or s.get("captured_from") != original.as_posix()
                    or s.get("applicability") != applicability
                    or s.get("qualification") != applicability
                    or snapshot is None or origin.resolve() != snapshot):
                errors.append("invalid frozen example provenance " + sid)
        elif (s.get("freshness") != "current-source"
              or s.get("kind") not in ("code", "instructions", "other skill")
              or origin.resolve().is_relative_to(root)
              or s.get("captured_from") != Path(s.get("origin", "")).as_posix()):
            errors.append("static source cannot be frozen " + str(sid))
    return errors


def provenance_html(source):
    frozen = source["freshness"] == "frozen-example"
    label = "Frozen historical example" if frozen else "Current authoritative source at capture"
    return (f'<aside class="source-provenance" data-source-freshness="{source["freshness"]}">'
            f'<p><strong>{label}</strong> · captured <time>{esc(source["captured_at"])}</time></p>'
            f'<p class="path">Captured from: {esc(source["captured_from"])}</p>'
            f'<p>{esc(source["applicability"])}</p>'
            f'<p class="path">Capture SHA-256: {source["sha256"]}</p></aside>')


def render_catalog(root, data):
    """Reuse the existing renderer and add visible capture identity to its pages."""
    render(root, data)
    sources = {s["id"]: s for s in data["sources"]}
    anchors = {a["id"]: a for a in data["anchors"]}
    for source in sources.values():
        page = root / "source-pages" / (source["id"] + ".html")
        body = page.read_text(encoding="utf-8")
        page.write_text(body.replace('<pre class="full-source">', provenance_html(source) + '<pre class="full-source">', 1), encoding="utf-8")
    for resource in data["resources"]:
        page = root / resource["target"]
        source = sources[anchors[resource["anchor_id"]]["source_id"]]
        body = page.read_text(encoding="utf-8")
        page.write_text(body.replace('<h2>Actual source</h2>', '<h2>Actual source</h2>' + provenance_html(source), 1), encoding="utf-8")
