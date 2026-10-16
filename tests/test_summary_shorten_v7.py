"""v7 Wave 1 — short, clean DISPLAYED summaries: plain-text normalizer + caps.

The cached summary text can carry markdown control sequences (``**bold**``,
``## headings``, backticks, list markers, ``[link](url)``) and decorative glyphs
(``✓ → ☢ • —`` …) that are fine on the rendered ``/summary`` markdown page but are
noise on the SHORT one-line objective / tile display. ``summarizer.short_summary_text``
(objective ≈ 140 chars) and ``summarizer.tile_blurb`` (≈ 64 chars) produce the clean,
capped plain-text form for those SHORT display sites ONLY.

These tests assert:
  1. each markdown / glyph class is stripped while the readable words survive,
  2. a clean sentence within the cap is returned UNCHANGED (no over-stripping),
  3. the length cap truncates on a word boundary with an ellipsis (and a short
     input is NOT truncated),
  4. whitespace is collapsed,
  5. the objective render site (home row + project-window header) now uses the
     normalizer (a glyph-laden cached summary renders a clean objective), and
  6. the full ``/summary`` markdown path is UNTOUCHED (markdown still present).

Hermetic: temp ANCHOR_DATA_DIR + reload, no live claude, no :8777, stdlib only.
"""
import importlib
import json
import re
from pathlib import Path

import pytest


# ── normalizer unit cases (no env needed) ────────────────────────────────────

@pytest.fixture(scope="module")
def summ():
    import summarizer
    importlib.reload(summarizer)
    return summarizer


# A grab-bag input exercising every strip class at once.
DIRTY = ("## Heading **Goal:** ship `code` X → handle ## edge cases ✓ "
         "— see [the doc](http://x/y) • done ☢")
# The readable words that MUST survive.
WORDS = ["Heading", "Goal", "ship", "code", "X", "handle", "edge", "cases",
         "see", "the", "doc", "done"]
# Glyph / markdown classes that must NOT survive.
BAD = ["**", "##", "`", "→", "✓", "•", "☢", "](", "[", "]", "—", "–"]


def test_each_glyph_and_markdown_class_stripped(summ):
    out = summ.short_summary_text(DIRTY)
    for bad in BAD:
        assert bad not in out, f"{bad!r} survived: {out!r}"
    for w in WORDS:
        assert w in out, f"{w!r} dropped: {out!r}"
    # The link label survives; the URL does NOT.
    assert "the doc" in out
    assert "http" not in out


def test_bold_underscore_backtick_list_link_blockquote(summ):
    assert summ.short_summary_text("**bold**") == "bold"
    assert summ.short_summary_text("__under__") == "under"
    assert summ.short_summary_text("`code span`") == "code span"
    assert summ.short_summary_text("- bullet item") == "bullet item"
    assert summ.short_summary_text("* star item") == "star item"
    assert summ.short_summary_text("1. numbered item") == "numbered item"
    assert summ.short_summary_text("2) paren item") == "paren item"
    assert summ.short_summary_text("[label](http://u)") == "label"
    assert summ.short_summary_text("> quoted line") == "quoted line"
    assert summ.short_summary_text("## Heading text") == "Heading text"


def test_dashes_normalized_to_hyphen(summ):
    out = summ.short_summary_text("ship X — handle edge cases")
    assert "—" not in out and "–" not in out
    assert "-" in out
    assert "ship X" in out and "handle edge cases" in out


def test_decorative_glyphs_dropped(summ):
    for g in ("✓", "✗", "→", "←", "☢", "•", "●", "▼", "◢"):
        out = summ.short_summary_text(f"alpha {g} beta")
        assert g not in out, f"{g!r} survived: {out!r}"
        assert "alpha" in out and "beta" in out


# ── clean text returned unchanged (no over-stripping) ────────────────────────

def test_clean_sentence_unchanged(summ):
    clean = "Runs the trio as durable sessions."
    assert summ.short_summary_text(clean) == clean


def test_clean_sentence_keeps_normal_punctuation(summ):
    # Apostrophes, quotes, parentheses, colon, digits, question mark must survive.
    clean = "John's plan (v7): does it ship 3 waves, or 4?"
    assert summ.short_summary_text(clean) == clean


# ── length cap + word-boundary truncation ────────────────────────────────────

def test_long_input_truncated_on_word_boundary_with_ellipsis(summ):
    words = " ".join(f"word{i}" for i in range(60))   # well over 140 chars
    out = summ.short_summary_text(words, max_chars=40)
    assert out.endswith("…")
    # Within the cap (the ellipsis is the only char past the word-boundary cut).
    assert len(out) <= 41
    # Word boundary: no partial token immediately before the ellipsis.
    body = out[:-1]
    assert not body.endswith(" ")
    # It did not cut mid-word: every retained token is a whole "wordN".
    assert all(re.fullmatch(r"word\d+", t) for t in body.split())


def test_short_input_not_truncated(summ):
    s = "Short objective."
    out = summ.short_summary_text(s, max_chars=140)
    assert out == s
    assert "…" not in out


def test_tile_blurb_shorter_cap(summ):
    long = ("Anchor runs the research, planning and build trio as durable, "
            "resumable Claude Code sessions per project.")
    blurb = summ.tile_blurb(long)        # default 64
    assert len(blurb) <= 65              # +1 for the ellipsis
    assert blurb.endswith("…")
    # And the longer objective form keeps more of it (different cap).
    obj = summ.short_summary_text(long)  # default 140
    assert len(obj) >= len(blurb)


# ── whitespace collapse ──────────────────────────────────────────────────────

def test_whitespace_collapsed(summ):
    out = summ.short_summary_text("alpha   beta\t\tgamma\n\ndelta")
    assert out == "alpha beta gamma delta"


# ── structured-dict input (claims joined like _summary_text) ─────────────────

def test_accepts_structured_dict_claims(summ):
    structured = {"claims": ["**Goal:** ship X", "handle ## edge `cases` ✓"]}
    out = summ.short_summary_text(structured)
    for bad in ("**", "##", "`", "✓"):
        assert bad not in out
    assert "ship X" in out and "edge" in out and "cases" in out


def test_empty_inputs(summ):
    assert summ.short_summary_text("") == ""
    assert summ.short_summary_text(None) == ""
    assert summ.short_summary_text({"claims": []}) == ""


# ── render-site integration: the objective uses the normalizer ───────────────

@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "summarizer", "session_registry",
                "sessions"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    importlib.reload(anchor_gui)
    import rnd_registry
    import summarizer
    return anchor_gui, rnd_registry, summarizer


def _write_cached_project_summary(summarizer, folder, pid, text):
    p = summarizer._project_summary_json_path(str(folder), pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": summarizer.SUMMARY_SCHEMA_VERSION,
        "summary_text": text,
        "summary": text,
        "no_grounded_claims": False,
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


GLYPHY = "## **Goal:** ship X — handle ## edge `cases` ✓ → done ☢ • now"


def test_home_row_objective_is_normalized(gui_env, tmp_path):
    gui, rnd, summ = gui_env
    folder = tmp_path / "Proj"
    folder.mkdir(parents=True, exist_ok=True)
    pid = rnd.add_project("Proj", str(folder))["id"]
    _write_cached_project_summary(summ, folder, pid, GLYPHY)

    row = gui.render_project_tile_html(rnd.get_project(pid))
    # Scope to the objective summary span (other row parts legitimately use a
    # dash in the "idle — no sessions yet" placeholder).
    m = re.search(r'<span class="rnd-row-summary"[^>]*>([\s\S]*?)</span>', row)
    assert m, "row summary span not rendered"
    summary_span = m.group(0)
    # The cached objective renders, but the markdown / decorative glyphs are gone.
    for bad in ("**", "—", "##", "`", "✓", "☢", "•"):
        assert bad not in summary_span, f"{bad!r} leaked into the home row objective: {summary_span!r}"
    # The readable words still show.
    assert "ship X" in summary_span and "edge" in summary_span and "cases" in summary_span


def test_project_window_header_objective_is_normalized(gui_env, tmp_path):
    gui, rnd, summ = gui_env
    folder = tmp_path / "Proj2"
    folder.mkdir(parents=True, exist_ok=True)
    pid = rnd.add_project("Proj2", str(folder))["id"]
    _write_cached_project_summary(summ, folder, pid, GLYPHY)

    html = gui.render_project_window_html(pid)
    # Pull out just the objective div so other (legitimately markdown-ish) parts
    # of the page don't cause false positives.
    m = re.search(r"<div class='proj-objective'[\s\S]*?</div>", html)
    assert m, "objective div not rendered"
    obj = m.group(0)
    for bad in ("**", "—", "##", "`", "✓", "☢", "•"):
        assert bad not in obj, f"{bad!r} leaked into the header objective: {obj!r}"
    assert "ship X" in obj and "edge" in obj and "cases" in obj


# ── negative: the FULL /summary markdown path is UNTOUCHED ───────────────────

def test_full_summary_markdown_still_has_formatting(summ):
    """The normalizer must NOT be applied to the full markdown render — the
    ``/summary`` page keeps its markdown (headings, bold, list markers)."""
    structured = {
        "lane": "build",
        "title": "Build session",
        "what_was_asked": "ship X",
        "prompts": ["do the thing"],
        "actions": [{"label": "anchor_gui.py"}],
    }
    md = summ.render_markdown(structured)
    # Full markdown formatting is intact (the short normalizer did not touch it).
    assert "**What was asked:**" in md
    assert "## Prompts asked" in md
    assert "- do the thing" in md
    assert "# Build session" in md
