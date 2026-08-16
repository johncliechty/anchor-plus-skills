"""The REFINE-THE-PLAN overlay backend: talk-to-edit DRAFT, section-scoped
HASH-BOUND confirm, and the drawn 'plan moved' card WITH diff
(steward-chamber W11, C7 — §overlays + AG-PLAN-MOVED).

**The law:** Refine talks in DRAFT — the plan store writes ONLY on a
hash-bound confirm (:func:`confirm_refine`), exactly as the locked mockup
states ("the ledger writes only on 'Confirm the plan' — the existing
hash-bound confirm"). The confirm is SECTION-SCOPED: it binds to the hash
of ONE plan section (:func:`section_hash`), so reflections, landings, and
edits to OTHER sections while the draft is open NEVER invalidate it — only
a genuine conflict in the SAME section does, and that conflict paints the
drawn AG-PLAN-MOVED card WITH a real unified diff
(:func:`plan_moved_card` / :func:`render_plan_moved_card_html`), the draft
PRESERVED — [Re-apply my draft on top] / [Take the new plan], never a
silent clobber.

**The plan store** (``.anchor/chamber/plan-refine.json``, chamber sidecar —
zero spine writes) holds the refineable plan SECTIONS as derived state,
seeded deterministically from the W4 sidecar pipeline manifest on first
read (:func:`plan_sections` — one section per manifest step by id, plus
``goal`` and ``deliverable``) and carrying every applied refinement
afterward. Durability rides ``chamber_projections`` (kernel file lock +
temp/fsync/rename) — the simulated-concurrent-writer test at steward-loop
cadence exercises exactly this store.

Failure states: store unreadable → named ``refine-store-unreadable`` error
(fails closed — no write); unknown section → ``unknown-section``; stale
bound hash → the 'plan moved' card (``plan-moved``), draft preserved;
empty-but-valid → a manifest-less project seeds zero sections and says so.

Stdlib only; no model call, no spawn, no network.
"""
from __future__ import annotations

import difflib
import hashlib
import html as _html
import json
import os
import time
from pathlib import Path

import chamber_projections as _cp

SCHEMA = "anchor-chamber-plan-refine-v1"

PLAN_REFINE_REL = os.path.join(_cp.CHAMBER_SIDECAR_REL, "plan-refine.json")
PLAN_REFINE_LOCK_REL = PLAN_REFINE_REL + ".lock"

#: Named errors / findings (refusals are named, never silent).
ERROR_STORE_UNREADABLE = "refine-store-unreadable"
ERROR_UNKNOWN_SECTION = "unknown-section"
ERROR_EMPTY_DRAFT = "empty-draft-text"
ERROR_PLAN_MOVED = "plan-moved"
FINDING_PLAN_MOVED = "W11-PLAN-MOVED-UNDER-DRAFT"

#: The drawn AG-PLAN-MOVED affordances (MOCKUP-AMENDMENT-GATE row 8).
PLAN_MOVED_TITLE = "⚑ Plan moved while you were drafting"
BTN_REAPPLY = "Re-apply my draft on top"
BTN_TAKE_NEW = "Take the new plan"

#: The drawn REFINE overlay chrome (§overlays, hash-pinned mockup).
OVERLAY_TITLE = "Refine the plan"
OVERLAY_SUBTITLE = "· nothing changes until you confirm"
BTN_CONFIRM = "Confirm the plan"
BTN_KEEP = "Keep refining"
BTN_DISCARD = "Discard draft"


class RefineStoreError(RuntimeError):
    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error = error


def store_path(folder) -> Path:
    return Path(folder) / PLAN_REFINE_REL


def _lock_path(folder) -> Path:
    return Path(folder) / PLAN_REFINE_LOCK_REL


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ═════════════════════════════════════════════════════════════════════════════
# The plan sections (derived from the W4 manifest; refinements applied on top)
# ═════════════════════════════════════════════════════════════════════════════

def _seed_sections(folder) -> dict:
    """Deterministic first-read seed from the sidecar pipeline manifest.
    A manifest-less / unparseable project seeds ZERO sections —
    empty-but-valid, never a guess."""
    try:
        import chamber_manifest as cm
        manifest = cm.load_manifest(folder)
    except Exception:
        manifest = None
    sections: dict = {}
    if not isinstance(manifest, dict) or "_unparseable" in manifest:
        return sections
    for step in (manifest.get("steps") or []):
        if isinstance(step, dict) and step.get("id"):
            sections[str(step["id"])] = {
                "text": json.dumps(step, ensure_ascii=False, sort_keys=True,
                                   indent=1),
                "seeded_from": "manifest.steps[%s]" % step["id"]}
    for key in ("goal", "deliverable"):
        if isinstance(manifest.get(key), (dict, str)):
            sections[key] = {
                "text": json.dumps(manifest[key], ensure_ascii=False,
                                   sort_keys=True, indent=1),
                "seeded_from": "manifest.%s" % key}
    return sections


def _empty_store(folder) -> dict:
    return {"schema": SCHEMA, "sections": _seed_sections(folder),
            "drafts": [], "applied": []}


def _load(folder) -> dict:
    p = store_path(folder)
    if not p.exists():
        return _empty_store(folder)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RefineStoreError(
            ERROR_STORE_UNREADABLE,
            "plan-refine store unreadable at %s: %s" % (PLAN_REFINE_REL, exc))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise RefineStoreError(
            ERROR_STORE_UNREADABLE,
            "plan-refine store carries no %r schema" % SCHEMA)
    doc.setdefault("sections", {})
    doc.setdefault("drafts", [])
    doc.setdefault("applied", [])
    return doc


def _save(folder, doc: dict) -> None:
    _cp.atomic_write_json(store_path(folder), doc)


def plan_sections(folder) -> dict:
    """The refineable sections as SAFE state: id → current text + hash."""
    try:
        doc = _load(folder)
    except RefineStoreError as exc:
        return {"ok": False, "error": exc.error}
    return {"ok": True, "schema": SCHEMA,
            "sections": {sid: {"hash": _hash_text(s.get("text") or ""),
                               "text": s.get("text") or ""}
                         for sid, s in (doc.get("sections") or {}).items()}}


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def section_hash(folder, section_id: str) -> str | None:
    """The SECTION-SCOPED hash a confirm binds to — sha256 over exactly this
    section's current text. None for an unknown section."""
    try:
        doc = _load(folder)
    except RefineStoreError:
        return None
    sec = (doc.get("sections") or {}).get(str(section_id))
    if sec is None:
        return None
    return _hash_text(sec.get("text") or "")


# ═════════════════════════════════════════════════════════════════════════════
# Draft (talk-to-edit; NOTHING writes to the plan here)
# ═════════════════════════════════════════════════════════════════════════════

def open_draft(folder, section_id: str, draft_text: str) -> dict:
    """Open (or replace) THE draft for one section, bound to the section's
    CURRENT hash. Drafts are talk-state: the plan itself is untouched."""
    sid = str(section_id or "").strip()
    text = str(draft_text or "")
    if not text.strip():
        return {"ok": False, "error": ERROR_EMPTY_DRAFT}
    with _cp.file_lock(_lock_path(folder)):
        try:
            doc = _load(folder)
        except RefineStoreError as exc:
            return {"ok": False, "error": exc.error, "message": str(exc)}
        sec = (doc.get("sections") or {}).get(sid)
        if sec is None:
            return {"ok": False, "error": ERROR_UNKNOWN_SECTION,
                    "section_id": sid,
                    "known": sorted((doc.get("sections") or {}).keys())}
        base_text = sec.get("text") or ""
        draft = {"section_id": sid, "text": text,
                 "base_hash": _hash_text(base_text),
                 "base_text": base_text, "opened_at": _now()}
        doc["drafts"] = [d for d in doc["drafts"]
                         if d.get("section_id") != sid] + [draft]
        _save(folder, doc)
    return {"ok": True, "draft": {"section_id": sid,
                                  "base_hash": draft["base_hash"]}}


def current_draft(folder, section_id: str) -> dict | None:
    try:
        doc = _load(folder)
    except RefineStoreError:
        return None
    for d in doc.get("drafts") or []:
        if d.get("section_id") == str(section_id):
            return dict(d)
    return None


def discard_draft(folder, section_id: str) -> dict:
    with _cp.file_lock(_lock_path(folder)):
        try:
            doc = _load(folder)
        except RefineStoreError as exc:
            return {"ok": False, "error": exc.error}
        before = len(doc.get("drafts") or [])
        doc["drafts"] = [d for d in doc["drafts"]
                         if d.get("section_id") != str(section_id)]
        _save(folder, doc)
    return {"ok": True, "discarded": before - len(doc["drafts"])}


# ═════════════════════════════════════════════════════════════════════════════
# The hash-bound confirm (THE ONLY plan write) + the 'plan moved' conflict
# ═════════════════════════════════════════════════════════════════════════════

def confirm_refine(folder, section_id: str, bound_hash: str,
                   new_text: str) -> dict:
    """Apply one refinement — IFF the bound section hash still matches.

    * Unrelated activity (other sections refined, reflections/landings
      appended, projection events written) NEVER invalidates the confirm:
      only THIS section's hash is checked — that is what section-scoped
      means, structurally.
    * A genuine same-section conflict returns the DRAWN 'plan moved' card
      (:data:`ERROR_PLAN_MOVED` + :data:`FINDING_PLAN_MOVED`) WITH a
      unified diff of base → current, and the draft is PRESERVED in the
      store — [Re-apply] / [Take the new plan] both stay possible.
    * The store writes ONLY on a matching hash (the mockup's law).
    """
    sid = str(section_id or "").strip()
    text = str(new_text or "")
    if not text.strip():
        return {"ok": False, "error": ERROR_EMPTY_DRAFT}
    with _cp.file_lock(_lock_path(folder)):
        try:
            doc = _load(folder)
        except RefineStoreError as exc:
            return {"ok": False, "error": exc.error, "message": str(exc)}
        sec = (doc.get("sections") or {}).get(sid)
        if sec is None:
            return {"ok": False, "error": ERROR_UNKNOWN_SECTION,
                    "section_id": sid,
                    "known": sorted((doc.get("sections") or {}).keys())}
        current = sec.get("text") or ""
        cur_hash = _hash_text(current)
        if str(bound_hash or "") != cur_hash:
            # The GENUINE conflict: this section moved under the draft.
            draft = None
            for d in doc.get("drafts") or []:
                if d.get("section_id") == sid:
                    draft = d
                    break
            base_text = (draft or {}).get("base_text") or ""
            card = plan_moved_card(sid, base_text, current,
                                   draft_text=(draft or {}).get("text")
                                   or text)
            # Draft preserved — nothing is written, nothing is dropped.
            return {"ok": False, "error": ERROR_PLAN_MOVED,
                    "finding": FINDING_PLAN_MOVED,
                    "section_id": sid,
                    "bound_hash": str(bound_hash or ""),
                    "current_hash": cur_hash,
                    "draft_preserved": draft is not None,
                    "card": card}
        # Hash-bound write: the ONE legitimate plan mutation. Only the
        # draft BEING APPLIED clears — another author's open draft on this
        # section survives (it now sits over a moved base: exactly the
        # AG-PLAN-MOVED situation its own confirm will surface).
        sec["text"] = text
        applied = {"section_id": sid, "from_hash": cur_hash,
                   "to_hash": _hash_text(text), "at": _now()}
        doc["applied"].append(applied)
        doc["drafts"] = [d for d in doc["drafts"]
                         if not (d.get("section_id") == sid
                                 and d.get("text") == text)]
        _save(folder, doc)
    _auto_commit(folder, "refine confirm: section %s" % sid)
    return {"ok": True, "applied": applied}


def _auto_commit(folder, label: str) -> None:
    """Best-effort campaign bank via the WIRED auto-commit (wire-homing row
    ``auto_commit`` — never reimplemented here).

    Banks ONLY when the project already carries a git repo: repo bootstrap
    belongs to project registration, not to a refine confirm — and confirms
    land at steward-loop cadence (the W11 concurrent-writer law), where an
    inline ``git init``/``add``/``commit`` subprocess storm per confirm
    would starve every other writer. A registered campaign folder is always
    a repo (project_bootstrap), so real campaigns still bank every confirm.
    """
    try:
        if not (Path(folder) / ".git").exists():
            return
        import commission_session as _cs
        _cs.commit_campaign_state(folder, label)
    except Exception:
        pass


def plan_moved_card(section_id: str, base_text: str, current_text: str, *,
                    draft_text=None) -> dict:
    """The AG-PLAN-MOVED card DATA: prose + the REAL unified diff (base →
    current) + the two drawn affordances. The diff is never empty prose —
    it is difflib's unified diff of what actually moved."""
    # The card's diff is the CHANGED-LINE pairs (the drawn card's del/add
    # rows); headers and context are dropped from the card — the full
    # unified diff is derivable from base/current, which both ride the
    # draft record.
    diff_lines = [
        ln for ln in difflib.unified_diff(
            str(base_text or "").splitlines(),
            str(current_text or "").splitlines(),
            lineterm="", n=0)
        if (ln.startswith("+") and not ln.startswith("+++"))
        or (ln.startswith("-") and not ln.startswith("---"))]
    return {
        "finding": FINDING_PLAN_MOVED,
        "title": PLAN_MOVED_TITLE,
        "section_id": str(section_id),
        "prose": "The plan re-shaped section '%s' under your draft. Your "
                 "draft is intact — review the change, then re-apply or "
                 "take the new plan." % section_id,
        "diff": diff_lines,
        "draft_preserved": True,
        "draft_text": draft_text,
        "actions": [BTN_REAPPLY, BTN_TAKE_NEW],
    }


# ═════════════════════════════════════════════════════════════════════════════
# The drawn renders (§overlays REFINE dock + AG-PLAN-MOVED) — F5-escaped
# ═════════════════════════════════════════════════════════════════════════════

def _esc(value) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def render_plan_moved_card_html(card: dict) -> str:
    """The drawn AG-PLAN-MOVED card: ``.decision`` > ``.who`` flag line +
    prose + ``.pmdiff`` with ``.del``/``.add`` rows + ``.act`` with the two
    signed affordances. Every slot escaped (F5); diff lines are TEXT."""
    c = card or {}
    rows = []
    for ln in (c.get("diff") or []):
        ln = str(ln)
        if not ln.startswith(("+", "-")):
            continue  # the drawn card carries del/add rows only
        cls = "add" if ln.startswith("+") else "del"
        rows.append('<span class="%s">%s</span>' % (cls, _esc(ln)))
    return (
        '<div class="decision" data-finding="%s">'
        '<div class="who">%s</div>'
        '%s'
        '<div class="pmdiff">%s</div>'
        '<div class="act">'
        '<button class="btn pri" data-refine-reapply="1">%s</button>'
        '<button class="btn" data-refine-take-new="1">%s</button>'
        '</div></div>'
        % (_esc(c.get("finding") or FINDING_PLAN_MOVED),
           _esc(c.get("title") or PLAN_MOVED_TITLE),
           _esc(c.get("prose") or ""),
           "\n".join(rows),
           _esc(BTN_REAPPLY), _esc(BTN_TAKE_NEW)))


def render_refine_overlay_html(view: dict) -> str:
    """The drawn REFINE overlay (§overlays): ``.page`` > ``.dock`` >
    ``.dbar`` (``.ti`` + ``small`` · ``.sp`` · ``.btn`` ×) > ``.msgs`` of
    ``.msg.john`` / ``.msg.steward`` (each with ``.who``), the final
    steward message carrying ``.act`` with [Confirm the plan] /
    [Keep refining] / [Discard draft]. A 'plan moved' conflict renders
    STANDALONE via :func:`render_plan_moved_card_html` (its ``.decision``
    root replaces the dock body — the drawn AG composition), never nested
    into the msgs column. Pure string render, every slot escaped (F5)."""
    v = view or {}
    msgs = []
    for m in (v.get("messages") or []):
        who = "john" if (m or {}).get("who") == "john" else "steward"
        label = "John" if who == "john" else _esc(v.get("steward_label")
                                                  or "Steward")
        msgs.append('<div class="msg %s"><div class="who">%s</div>%s</div>'
                    % (who, label, _esc((m or {}).get("text"))))
    confirm = (
        '<div class="msg steward"><div class="who">%s</div>%s'
        '<div class="act">'
        '<button class="btn pri" data-refine-confirm="1">%s</button>'
        '<button class="btn" data-refine-keep="1">%s</button>'
        '<button class="btn" data-refine-discard="1">%s</button>'
        '</div></div>'
        % (_esc(v.get("steward_label") or "Steward"),
           _esc(v.get("summary") or "Nothing is drafted yet — talk to "
                                    "edit; the plan writes only on your "
                                    "confirm."),
           _esc(BTN_CONFIRM), _esc(BTN_KEEP), _esc(BTN_DISCARD)))
    return (
        '<div class="page" style="background:rgba(0,0,0,.25)">'
        '<div class="dock" style="max-width:520px;margin:8px auto">'
        '<div class="dbar">'
        '<span class="ti">%s <small>%s</small></span>'
        '<span class="sp"></span>'
        '<button class="btn" data-overlay-close="1">×</button>'
        '</div>'
        '<div class="msgs" style="padding:12px 16px;display:flex;'
        'flex-direction:column;gap:8px">%s%s</div>'
        '</div>'
        '</div>'
        % (_esc(OVERLAY_TITLE), _esc(OVERLAY_SUBTITLE),
           "".join(msgs), confirm))


#: The drawn base signatures a painted REFINE overlay MUST contain (the
#: required direction of the C9 diff — an empty dock can never diff green).
#: Consumed by the W11 CI diff via chamber_mockup_diff.missing_required.
REQUIRED_REFINE_OVERLAY = (
    ("div", ("page",)), ("div", ("dock",)), ("div", ("dbar",)),
    ("span", ("ti",)), ("small", ()), ("span", ("sp",)),
    ("button", ("btn",)), ("div", ("msgs",)),
    ("div", ("msg", "steward")), ("div", ("who",)),
    ("div", ("act",)), ("button", ("btn", "pri")),
)

#: And the drawn plan-moved card's own required signatures (AG-PLAN-MOVED).
REQUIRED_PLAN_MOVED = (
    ("div", ("decision",)), ("div", ("who",)), ("div", ("pmdiff",)),
    ("div", ("act",)), ("button", ("btn", "pri")), ("button", ("btn",)),
)
