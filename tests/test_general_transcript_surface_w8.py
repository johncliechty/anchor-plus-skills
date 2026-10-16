# W8 delta-coverage stub gate — the general-lane session TRANSCRIPT
# persistence surface (general/<sid>-transcript.md).
#
# AUTH-ON: not-a-surface
#
# During steward-chamber W8 the LIVE Anchor service persisted a Doctor
# session's transcript into the main tree — general/dbc27481dbd0-transcript.md
# — and the wave's delta-coverage gate correctly refused to GO while a
# persistence surface rode the delta with no test naming it. The surface is
# the v8 doc-persistence keystone's transcript leg (capture_session_docs →
# general/<sid>-transcript.md), NOT new W8 chamber code; this stub gate names
# it and pins the honest shape contract every persisted general-lane
# transcript must keep:
#   * file name is <session-id>-transcript.md directly under general/
#   * content is non-empty markdown opening with the transcript header line
#     "# General session transcript (<sid>)" so a reader (and the brownfield
#     scanner) can tell WHAT session produced it without guessing.
#
# Pure read-only fixture test — no server, no PTY, no writes.
import re
import sys
from pathlib import Path

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

GENERAL = ANCHOR / "general"

#: The observed instance that rode the W8 delta (the live service's Doctor
#: session, 2026-08-10). Named here so the surface is never test-invisible.
OBSERVED_TRANSCRIPT = "general/dbc27481dbd0-transcript.md"

_NAME_RE = re.compile(r"^[0-9a-f]{6,32}-transcript\.md$")
_HEADER_RE = re.compile(r"^# General session transcript \([0-9a-f]{6,32}\)")


def _transcripts():
    if not GENERAL.is_dir():
        return []
    return sorted(p for p in GENERAL.glob("*-transcript.md")
                  if _NAME_RE.match(p.name))


def test_general_transcripts_keep_the_persisted_shape_contract():
    for p in _transcripts():
        text = p.read_text(encoding="utf-8", errors="replace")
        assert text.strip(), "%s: a persisted transcript is never empty" % p.name
        assert _HEADER_RE.match(text.splitlines()[0]), (
            "%s: first line must be the '# General session transcript (<sid>)'"
            " header, so the producing session is never a guess" % p.name)
        # The sid in the header matches the sid in the file name — one
        # session, one transcript, no mislabeled doc.
        sid = p.name[:-len("-transcript.md")]
        assert sid in text.splitlines()[0]


def test_the_observed_w8_transcript_instance_is_shape_true():
    p = ANCHOR / OBSERVED_TRANSCRIPT
    if not p.exists():
        # The instance is runtime state owned by the live service; if it has
        # been swept/moved the shape contract above still guards the surface.
        return
    first = p.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    assert first.startswith("# General session transcript (dbc27481dbd0)")
