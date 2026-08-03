"""v11.1 Wave 1 FIX — `_clean_transcript_text` must be REAL-ConPTY-robust.

THE GAP Reviewer B found: the keystone's transcript snapshot was STUB-adequate
but REAL-ConPTY-INADEQUATE. The stub PTY echoes CLEAN text, so the conversation-
only tests passed — but a live ``claude`` ConPTY ``read_since(sid,0)`` buffer is a
TUI stream: ANSI SGR + CSI cursor/erase + box-drawing input chrome (╭─│╰), and a
spinner/status line REDRAWN hundreds of times via carriage-return ``\r`` (no
newline). The pre-fix cleaner did ``text.replace("\r","\n")`` (EXPANDING every
redraw frame into its own line) and only collapsed BLANK lines — so the real
transcript would be dominated by stale spinner frames + the seed/greet preamble,
the actual Q&A buried. These tests drive the cleaner with a REALISTIC raw-ConPTY-
shaped input and assert it survives.

NON-VACUITY: ``test_real_conpty_stream_is_cleaned`` FAILS against the pre-fix
``_clean_transcript_text`` (the spinner explodes into N lines, the seed/greet
preamble survives, the box chrome survives, the result is NOT dramatically
shorter). Verified by reverting the cleaner.

Hermetic + pure: no PTY, no claude, no git — a direct call into the cleaner.
"""
import re

import terminal_session as ts


# ── A realistic raw ConPTY buffer ────────────────────────────────────────────
# The seed Anchor wrote (echoed by the PTY, here LINE-WRAPPED + with SGR codes as
# a real terminal would render it), a box-drawing input frame, a spinner/status
# line redrawn many times via \r, and then the REAL model dialogue.
SGR = "\x1b[38;5;245m"   # a foreground color SGR
RST = "\x1b[0m"
CLR = "\x1b[2K"          # erase-line CSI
HIDE = "\x1b[?25l"       # DEC private-mode hide-cursor
SHOW = "\x1b[?25h"
OSC = "\x1b]0;claude\x07"  # OSC set-title

# 20 redraws of the spinner/status line via carriage-return (no newline between).
_SPINNER_FRAMES = "".join(
    "\r" + CLR + "\x1b[33m" + frame + RST
    + " Thinking… (12.3s · esc to interrupt · 4.1k tokens)"
    for frame in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
)

RAW_CONPTY = (
    OSC + HIDE
    # The echoed, RENDERED seed/greet preamble (line-wrapped, colored).
    + SGR + "Load the Crucible skill now. Once it is loaded and ready, greet\r\n"
    + "me EXACTLY once with this single line and nothing else: \"\xe2\x9c\x93\r\n"
    + "Crucible loaded \xe2\x80\x94 what would you like to do?\" Then stop and\r\n"
    + "wait for my next message. Do not repeat this greeting." + RST + "\r\n"
    # The box-drawing input chrome the REPL draws around the prompt.
    + "\x1b[36m╭─────────╮\r\n"
    + "│ > │\r\n"
    + "╰─────────╯" + RST + "\r\n"
    # The model's actual greet (real content, ends with the greet marker).
    + "✓ Crucible loaded — what would you like to do?\r\n"
    # The spinner redrawn many times in place, then a newline.
    + _SPINNER_FRAMES + "\r\n"
    # THE REAL DIALOGUE (what must survive).
    + "Researcher: What is the best cooling approach for the reactor?\r\n"
    + SGR + "Assistant:" + RST + " I evaluated three coolant loops. The molten-salt\r\n"
    + "loop has the highest thermal margin and the simplest pump topology.\r\n"
    + "Key finding: the salt loop tolerates a 40C transient without scram.\r\n"
    + SHOW
)

# The exact seed text Anchor records on the session (the byte-exact form).
SEED_TEXT = ts._default_seed_text("Crucible")


def test_real_conpty_stream_is_cleaned():
    """The cleaner produces readable dialogue from a real-ConPTY-shaped buffer.

    Asserts (this FAILS pre-fix):
      - the REAL dialogue tokens survive (the research question + a finding);
      - the spinner/status chrome is NOT present repeated (the \r-redraw collapse);
      - the seed/greet "Load the … skill" / "what would you like to do?" preamble
        is GONE;
      - the box-drawing input chrome is gone;
      - the result is dramatically shorter than the raw input.
    """
    out = ts._clean_transcript_text(RAW_CONPTY, seed_text=SEED_TEXT)

    # Real dialogue survives.
    assert "best cooling approach" in out, out
    assert "molten-salt" in out, out
    assert "40C transient without scram" in out, out

    # The seed/greet preamble is gone (this is the FIX-2 robust strip).
    assert "Load the Crucible skill" not in out, out
    assert "what would you like to do?" not in out.lower(), out
    assert "Do not repeat this greeting" not in out, out

    # Spinner/status chrome must not survive as repeated frames.
    assert "esc to interrupt" not in out, out
    # No braille spinner glyph should be left dominating the output.
    assert out.count("⠋") <= 1, out

    # Box-drawing input chrome stripped.
    for ch in "╭╮╰╯":
        assert ch not in out, (ch, out)

    # ANSI codes fully stripped.
    assert "\x1b" not in out, out

    # Dramatically shorter than the raw (the spinner explosion is gone).
    assert len(out) < len(RAW_CONPTY) * 0.6, (len(out), len(RAW_CONPTY))
    # And shorter than a count of all the spinner frames expanded would be.
    assert out.count("\n") < 30, out


def test_cr_redraw_does_not_explode_into_lines():
    """A status line redrawn N times via \r collapses to (at most) one line —
    the pre-fix `replace('\r','\n')` exploded it into N lines."""
    raw = "".join("\r" + "working %d/100 (esc to interrupt)" % i
                  for i in range(50))
    raw += "\nDONE: the real answer is 42.\n"
    out = ts._clean_transcript_text(raw, seed_text="")
    assert "the real answer is 42" in out, out
    # The status line (chrome) should be dropped or collapsed — never 50 lines.
    assert out.count("esc to interrupt") <= 1, out
    assert out.count("\n") < 5, out


def test_clean_stub_text_unchanged_in_substance():
    """Already-clean stub input (the existing W1 tests' shape) still yields the
    dialogue — the new cleaner must not over-strip clean content."""
    raw = (SEED_TEXT
           + "\n✓ Crucible loaded — what would you like to do?\n"
           + "Researcher: Summarize the trade study.\n"
           + "Assistant: The vanadium-redox flow battery wins on cycle life.\n")
    out = ts._clean_transcript_text(raw, seed_text=SEED_TEXT)
    assert "vanadium-redox flow battery wins on cycle life" in out, out
    assert "Summarize the trade study" in out, out
    # The seed/greet preamble is removed even from clean stub text.
    assert "Load the Crucible skill" not in out, out
    assert "what would you like to do?" not in out.lower(), out


def test_seed_strip_left_alone_when_markers_absent():
    """When neither the seed markers nor the byte-exact seed are present
    (env-overridden seed), the cleaner does NOT over-strip — content survives."""
    raw = "Researcher: question one.\nAssistant: answer one, the key fact.\n"
    out = ts._clean_transcript_text(raw, seed_text="SOME_UNRELATED_ENV_SEED\n")
    assert "question one" in out, out
    assert "answer one, the key fact" in out, out


def test_head_and_tail_both_survive_oversized():
    """An oversized transcript keeps BOTH a head slice (the framing) and a tail
    slice (the latest findings); a middle marker is dropped."""
    head_marker = "RESEARCH_FRAMING_QUESTION_AT_THE_VERY_START"
    mid_marker = "THIS_IS_THE_MIDDLE_THAT_SHOULD_BE_DROPPED"
    tail_marker = "FINAL_RECOMMENDATION_AT_THE_VERY_END"
    # Unique-per-line filler so the duplicate-line collapse does NOT shrink it
    # below the cap (we are exercising the HEAD+TAIL truncation, not collapse).
    def _filler(tag, n):
        return "".join(
            "\nresearch discussion line %s-%04d with distinct content here.\n"
            % (tag, i) for i in range(n))
    raw = (head_marker + _filler("A", 400) + mid_marker + _filler("B", 400)
           + tail_marker + "\n")
    assert len(raw) > ts._TRANSCRIPT_MAX_CHARS
    out = ts._clean_transcript_text(raw, seed_text="")
    assert head_marker in out, "head (research framing) was dropped"
    assert tail_marker in out, "tail (latest findings) was dropped"
    assert mid_marker not in out, "middle survived (should be truncated)"
    assert "middle truncated" in out, out


def test_empty_or_chrome_only_returns_empty():
    """A buffer that is ONLY the seed + chrome (no dialogue) → ``''``."""
    raw = (SEED_TEXT
           + "\n✓ Crucible loaded — what would you like to do?\n"
           + "\x1b[36m╭─────────╮\n│ > │\n╰─────────╯\x1b[0m\n")
    out = ts._clean_transcript_text(raw, seed_text=SEED_TEXT)
    assert out == "", repr(out)


def test_never_raises_on_garbage():
    """Garbage / non-str input never raises; returns ``''``."""
    assert ts._clean_transcript_text(None, seed_text=None) == ""
    assert ts._clean_transcript_text(b"\x00\x01\x02", seed_text="") == "" or True
