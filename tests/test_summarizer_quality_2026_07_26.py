"""Summarizer quality tests (2026-07-26 hardening, P1.3 + P1.4).

Two defects found by the hardening review
(planning/anchor-hardening-2026-07-26/FINDINGS-BCD.md section B):

1. BLANKS. When member artifacts do not resolve on disk the grounding corpus
   collapses to little more than member titles, so every sentence the model
   writes fails the ratio and the tile renders "no grounded claims" — the
   outcome for ~60% of summaries on disk, including the home dashboard's own.
   It was not free: one zombie tile burned 194,422 tokens / 66.6s for a blank.
2. DUPLICATION. "Generate twice for validation" was implemented as a UNION that
   deduped only on exact text, so two paraphrases of one paragraph BOTH
   survived — ~700-word project summaries saying one thing twice.
"""
import summarizer as sm


# ── P1.3: never spend model calls on a corpus that cannot ground anything ────

def test_a_titles_only_session_seed_cannot_ground():
    """doc_chars == 0 means the corpus is member TITLES alone."""
    assert sm.seed_can_ground({"text": "build session", sm.SEED_DOC_CHARS: 0}) is False


def test_a_small_but_real_corpus_can_ground():
    """Small is not empty — a short real doc must still summarize."""
    assert sm.seed_can_ground({"text": "a short doc", sm.SEED_DOC_CHARS: 25}) is True


def test_a_seed_without_the_key_fails_open():
    """Fail OPEN: a missing key must never silently suppress summaries."""
    assert sm.seed_can_ground({"text": "legacy seed"}) is True


def test_a_project_grounds_on_labels_without_documents():
    """A project may ground its objective in deliverable names + lane activity."""
    assert sm.seed_can_ground(
        {"kind": "project", "text": "anchor_gui.py / researchPrime r-act-1",
         sm.SEED_DOC_CHARS: 0}) is True
    assert sm.seed_can_ground(
        {"kind": "project", "text": "   ", sm.SEED_DOC_CHARS: 0}) is False


def test_the_session_seed_reports_doc_chars():
    """The gate is only as good as the field — a real seed must carry it."""
    seed = sm.extraction_seed(".", "p1", "research",
                              {"title": "t", "member_files": []})
    assert seed[sm.SEED_DOC_CHARS] == 0, "no members ⇒ no document bytes"


def test_an_ungroundable_session_is_not_cached(tmp_path, monkeypatch):
    """The skip must NEVER be cached.

    A session's documents are persisted around the same moment the finish hook
    fires, so an ungroundable read can simply mean we looked too early. Caching
    it would freeze the blank tile forever — the very defect this fixes. The
    skip is free, so re-evaluating later is free, and it self-heals.
    """
    def _boom(*a, **k):
        raise AssertionError("model called on an ungroundable corpus")

    monkeypatch.setattr(sm, "_generate_candidates", _boom)
    folder = tmp_path / "proj"
    folder.mkdir()
    out = sm.summarize_session(folder, "p1", "planning",
                               {"session_id": "s1", "title": "No docs",
                                "member_files": []})
    assert out["claims"] == []
    assert out["no_grounded_claims"] is True
    assert out["ungroundable"] is True
    assert out["runs"] == 0, "no model run happened, so runs must be 0"
    assert sm.load_cached(folder, "p1", "planning", "s1") is None,         "an ungroundable skip was cached — the blank tile is now permanent"


# ── P1.4: run two is a JUDGE, not a second author ────────────────────────────

def test_near_duplicate_paraphrases_collapse_to_one():
    """The live shape: one project summary restating itself in other words."""
    a = ("Anchor is a personal productivity and R and D command system running "
         "as a persistent local web server")
    b = ("Anchor is a personal productivity and R and D command system built "
         "for the author running as a persistent local web server daily")
    out = sm._collapse_near_duplicates([a, b])
    assert len(out) == 1, "two paraphrases of one claim must not both survive"
    assert out[0] == b, "the longer, more informative wording is kept"


def test_distinct_claims_are_preserved():
    claims = [
        "the trio drives research planning and build lanes through headless jobs",
        "the zombie hunter classifies token spending processes in shadow mode",
        "friction journaling feeds the sleep cycle intake brief",
    ]
    assert sm._collapse_near_duplicates(claims) == claims


def test_collapse_is_order_stable_and_deterministic():
    claims = ["alpha beta gamma delta epsilon", "zeta eta theta iota kappa",
              "alpha beta gamma delta epsilon zeta"]
    first = sm._collapse_near_duplicates(claims)
    assert sm._collapse_near_duplicates(claims) == first
    assert first[0].startswith("alpha")


def test_validate_applies_the_collapse(monkeypatch):
    """The union path itself must not emit two wordings of one claim."""
    monkeypatch.setattr(sm, "is_grounded", lambda *a, **k: True)
    a = "the summarizer generates twice and validates the claims it keeps"
    b = "the summarizer generates twice and then validates every claim it keeps"
    out = sm._validate([[a], [b]], {"text": "irrelevant, grounding stubbed"})
    assert len(out) == 1, "cross-run paraphrases must be collapsed, not concatenated"


def test_claims_without_content_tokens_are_not_dropped():
    """Degenerate input must never silently vanish."""
    assert sm._collapse_near_duplicates(["...", "!!!"]) == ["...", "!!!"]
