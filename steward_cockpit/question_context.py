"""Plain-data snapshots of a question and the response that explains it.

These helpers neither render HTML nor interpret saved text as instructions.
Authorization scope is retained as data; saving a question grants no authority.
"""

import hashlib
import json
import re


MAX_CONTEXT_CHARS = 12_000

#: Phrases that mark a real recommendation, checked over the TAIL of the turn
#: only (where the decision lives). Deliberately NARROW after the 2026-08-26
#: review: a false POSITIVE silently disables the check, which is the
#: expensive direction. Dropped from an earlier draft: bare "recommended"
#: (matches "as recommended by the plan") and "my call" (matches the exact
#: opposite sentence, "that's not my call - it's yours"). ONE matcher for the
#: engine's decision-shape check and the saved record (cockpit Wave C).
RECOMMEND_RE = re.compile(
    r"\b(i\s*(?:'|\u2019)?\s*(?:d|would)?\s*(?:recommend|suggest|propose)"
    r"|i\s*(?:'|\u2019)?\s*d?\s*lean\s+toward"
    r"|i\s*(?:'|\u2019)?\s*d?\s*go\s+with"
    r"|i\s+think\s+we\s+should|my\s+recommendation|my\s+advice\s+is"
    r"|recommendation\s*[:\u2014-]|the\s+right\s+move\s+is)", re.I)

#: How much of the turn tail counts as "where the decision is stated".
RECOMMEND_TAIL = 1200
_BULLET_RE = re.compile(r"^\s*[-*•·]\s*")
AUTHORIZES_RE = re.compile(r"^\s*(?:this\s+)?authoriz(?:es|ation)\s*[:\-\u2013\u2014]\s*(.+?)\s*$", re.I | re.M)
DECIDE_BY_RE = re.compile(r"^\s*decide\s+by\s*:\s*(.+?)\s*$", re.I | re.M)
REVERSIBLE_RE = re.compile(r"^\s*reversible\s*:\s*(yes|no)\b\s*(?:[,;\-\u2013\u2014]+\s*undo\s*:\s*(.+?))?\s*$", re.I | re.M)

_LIST_MARK = re.compile(r"^(?:#{1,6}\s+|[-*+\u2022]\s+|\d+[.)]\s+)")


def _clean(line):
    """Markdown markers out of a line, the words kept (for matching only)."""
    return _LIST_MARK.sub("", line.strip()).replace("**", "").replace("__", "").strip()


def _sentences(text):
    """(verbatim, cleaned, from_bullet) per sentence, line boundaries kept."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        bullet = bool(_LIST_MARK.match(line.strip()))
        for i, part in enumerate(re.split(r"(?<=[.!?])\s+", line.strip())):
            if part.strip():
                out.append((part.strip(), _clean(part), bullet and i == 0))
    return out


def question_line(text):
    """The last sentence that asks (ends with a question mark), or ''."""
    for verbatim, cleaned, _bullet in reversed(_sentences(text or "")):
        if cleaned.endswith("?"):
            return verbatim[:300]
    return ""


def parse_decision(text):
    """The decision shape read from the TAIL of a turn, before its last question:
    the recommendation (the last marker sentence with words beyond the marker),
    why (the sentence after it), the alternatives (bullet lines between the
    recommendation and the question, at most three) and the stake (up to three
    sentences before the recommendation - John reads two or three, as bullets). Verbatim, bounded; "" / [] when absent."""
    sents = _sentences((text or "")[-RECOMMEND_TAIL:])
    q_idx = next((i for i in range(len(sents) - 1, -1, -1) if sents[i][1].endswith("?")), None)
    scan_end = q_idx if q_idx is not None else len(sents)
    rec_idx = None
    for i in range(scan_end - 1, -1, -1):
        m = RECOMMEND_RE.search(sents[i][1])
        if m and re.search(r"\w", sents[i][1][m.end():]):
            rec_idx = i
            break
    out = {"stake": [], "recommendation": "", "why": "", "alternatives": [], "authorizes": "", "decide_by": "",
           "reversible": None, "undo": ""}
    tail = (text or "")[-RECOMMEND_TAIL:]
    hits = AUTHORIZES_RE.findall(tail)
    if hits:
        out["authorizes"] = hits[-1][:160]
    hits = DECIDE_BY_RE.findall(tail)
    if hits:
        out["decide_by"] = hits[-1][:80]
    hits = REVERSIBLE_RE.findall(tail)          # "Reversible: yes - undo: <how>" / "Reversible: no"
    if hits:
        out["reversible"] = hits[-1][0].lower() == "yes"
        out["undo"] = (hits[-1][1] or "").strip()[:200]
    if rec_idx is None:
        return out
    out["recommendation"] = sents[rec_idx][0][:240]
    out["stake"] = [v[:240] for v, c, _b in sents[max(0, rec_idx - 3):rec_idx] if not c.endswith("?")][:3]
    after = sents[rec_idx + 1:scan_end]
    if after and not after[0][2] and not after[0][1].endswith("?"):
        out["why"] = after[0][0][:200]
        after = after[1:]
    out["alternatives"] = [_BULLET_RE.sub("", v)[:160] for v, c, b in after if b and not c.endswith("?")][:3]
    return out


def has_recommendation(text) -> bool:
    """True when a decision turn actually carried a recommendation (the tail
    only: a recommendation buried in a long narrative is not one about the
    question asked at the end)."""
    return bool(parse_decision(text)["recommendation"])


def _json_copy(value):
    """Copy JSON data without silently widening an invalid authorization scope."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _source_window(response_text, question):
    if len(response_text) <= MAX_CONTEXT_CHARS:
        return response_text, False

    position = response_text.rfind(question)
    if position < 0:
        start = 0
    else:
        surrounding = max(0, MAX_CONTEXT_CHARS - len(question))
        start = max(0, position - surrounding // 2)
        start = min(start, len(response_text) - MAX_CONTEXT_CHARS)
    return response_text[start:start + MAX_CONTEXT_CHARS], True


def save_question_context(question, response_text, *, asked_at, source_ref="", scope=None,
                          origin_id=None, what_changed=None):
    """Return a JSON snapshot, preserving the question and original source ref.

    ``context`` is a literal source substring of at most 12,000 characters.
    When shortened, its window includes the question if the question occurs in
    the source and fits. The separate ``question`` field is always exact, even
    for questions longer than that bound. ``truncated`` signals lost context.

    The stable ID binds question, source reference, and JSON authorization scope
    minus the turn (``source_turn_id``): the same question asked again on the
    same work is the same question; a changed timestamp, context window or turn
    alone does not create a new identity. ``origin_id`` (a reshaped re-ask of the
    same decision) makes THAT the identity: the shape changed, the decision did
    not. ``what_changed`` is the open question this one replaces. Invalid strings
    or non-JSON scope/timestamps raise TypeError or ValueError.
    """
    if not isinstance(question, str) or not isinstance(response_text, str):
        raise TypeError("question and response_text must be strings")
    if not question.strip():
        raise ValueError("question must not be empty")
    if not isinstance(source_ref, str):
        raise TypeError("source_ref must be a string")

    authorization_scope = _json_copy(scope)
    context, truncated = _source_window(response_text, question)
    identity = json.dumps(
        [question, source_ref, {k: v for k, v in authorization_scope.items() if k != "source_turn_id"}
         if isinstance(authorization_scope, dict) else authorization_scope],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    shape = parse_decision(response_text)
    origin = origin_id if isinstance(origin_id, str) and re.fullmatch(r"[0-9a-f]{64}", origin_id) else None
    return {
        "id": origin or hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "question": question,
        "context": context,
        "truncated": truncated,
        "stake": shape["stake"],
        "recommendation": shape["recommendation"],
        "why": shape["why"],
        "alternatives": shape["alternatives"],
        "authorizes": shape["authorizes"],
        "decide_by": shape["decide_by"],
        "reversible": shape["reversible"],
        "undo": shape["undo"],
        "authorization_scope": authorization_scope,
        "asked_at": _json_copy(asked_at),
        "source_ref": source_ref,
        "origin_id": origin,
        "what_changed": str(what_changed)[:400] if isinstance(what_changed, str) else None,
    }


def normalize_question_context(value):
    """Normalize a saved dictionary or legacy question string; otherwise None.

    Unknown fields and supplied IDs are not trusted. Invalid JSON scope causes
    rejection rather than replacement with a broader scope. Existing truncation
    remains visible, and explicit saved recommendations remain plain strings.
    """
    if isinstance(value, str):
        value = {"question": value}
    if not isinstance(value, dict):
        return None
    question = value.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    context = value.get("context", value.get("response_text", ""))
    source_ref = value.get("source_ref", "")
    try:
        normalized = save_question_context(
            question,
            context if isinstance(context, str) else "",
            asked_at=value.get("asked_at"),
            source_ref=source_ref if isinstance(source_ref, str) else "",
            scope=value.get("authorization_scope", value.get("scope")),
            origin_id=value.get("origin_id"), what_changed=value.get("what_changed"),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    normalized["truncated"] = normalized["truncated"] or value.get("truncated") is True
    recommendation = value.get("recommendation")
    if isinstance(recommendation, str) and has_recommendation(recommendation):
        normalized["recommendation"] = recommendation.strip()[:240]
    if isinstance(value.get("why"), str) and value["why"].strip():
        normalized["why"] = value["why"].strip()[:240]
    stake = value.get("stake")
    if isinstance(stake, str) and stake.strip():
        stake = [stake]
    if isinstance(stake, list) and stake:
        normalized["stake"] = [item.strip()[:240] for item in stake if isinstance(item, str) and item.strip()][:3]
    alternatives = value.get("alternatives")
    if isinstance(alternatives, list) and alternatives:
        normalized["alternatives"] = [item[:160] for item in alternatives if isinstance(item, str)][:3]
    for key, cap in (("authorizes", 160), ("decide_by", 80)):
        if isinstance(value.get(key), str) and value[key].strip():
            normalized[key] = value[key].strip()[:cap]
    # W2 (High Seat, 2026-09-26): what the decision depends on, as the steward names it — register rows
    # by their What text, or plain names; the page links the ones it can resolve. At most six.
    depends = value.get("depends_on")
    if isinstance(depends, str) and depends.strip():
        depends = [depends]
    if isinstance(depends, list):
        cleaned = [item.strip()[:200] for item in depends if isinstance(item, str) and item.strip()]
        if cleaned:
            normalized["depends_on"] = cleaned[:6]
    return normalized
