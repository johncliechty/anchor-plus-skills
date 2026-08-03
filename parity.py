#!/usr/bin/env python3
"""Anchor journal↔legacy parity gate — the C3 proof surface (rearch W14).

The C3 spine dual-writes every mutation of record: a journal event FIRST
(:mod:`journal`), then the legacy store write. This module is the mandatory
CONSUMER that proves the two stay in agreement — the **quiescent classifying
parity gate** the frozen plan (``IMPLEMENTATION-PLAN.md`` W14) requires, wired
into the test suite AND the nightly healthcheck.

What it does (the W14 deliverable):

* **Derive two views from a WRITE_LOCK-bracketed snapshot.** Under
  :data:`paths.WRITE_LOCK` (so the journal and the legacy stores are read as one
  consistent instant), it snapshots the per-project journal events and the
  legacy stores into memory, then derives, from each, a **session view**
  (``{session_id: {lane, status}}``) and an **effort view** (the grass lane's
  ordered ``index.json`` membership — the one effort index the journal carries at
  job-id granularity; see the scope note below).
* **Classify every divergence** into exactly one of three classes:
    - :data:`CLASS_JOURNAL_AHEAD` — present in the journal, absent from the
      legacy store. **Benign** (severity ``ok``): journal-first means a crash
      *between* the emit and the legacy write leaves the journal one intent
      ahead; it is replayable idempotently and is never a lost legacy write.
      Tolerated outright inside the **bounded tail window** (the last
      ``tail_window`` seqs — the in-flight dual-writes at the tip).
    - :data:`CLASS_LEGACY_AHEAD` — present in the legacy store, absent from the
      journal. **BUG** (severity ``bug``): a store was mutated without its paired
      journal event — a C3 completeness violation.
    - :data:`CLASS_CONFLICT` — present in both but with a differing state
      (e.g. the journal says a session is ``running`` while the store says
      ``done``). **BUG**.
* **Report ``zero divergence``, bounded-tail-tolerant.** :class:`ParityReport`
  exposes the classified rows, the bugs, and ``is_clean(tail_window)`` — no bugs
  and no journal-ahead beyond the tail. A quiescent walk (every dual-write
  settled before the gate runs) reports zero divergence at ``tail_window=0``.

── Scope note (honest limitation, by the shape of the W13 payloads) ──────────

The effort-view parity + rebuild cover the **grass** lane index and the
**session** rows, because those are the mutation classes whose W13 journal
events carry the record's identity in their payload
(``grass-idea-added``/``effort-promoted`` carry the idea/job id;
``session-*`` carry the ``session_id``). The other effort lanes'
``doc-persisted`` events journal at LANE granularity only (the per-doc
content-addressed job ids are computed inside the persist loop, not in the
payload), so their exact ``index.json`` membership is not reconstructable from
the journal alone — those indexes are instead recovered from their surviving
per-effort pointer-records (``tools/rebuild_index.py``,
``source="pointers"``). This module therefore compares ONLY the lanes it can
fully derive from the journal, so a legitimately-journaled non-grass mutation is
never mis-classified as ``legacy-ahead``.

Stdlib only. Reads :mod:`journal`, :mod:`session_registry`,
:mod:`effort_history`, :mod:`rnd_registry`, :mod:`paths` — writes nothing (it is
a pure classifier; the recovery tools in :mod:`tools.rebuild_index` /
:mod:`tools.replay_journal` are the only mutators).
"""

from __future__ import annotations

from pathlib import Path

import paths as _paths
import journal as _journal

# ── Divergence classes + severity ────────────────────────────────────────────

#: Journal has the entity/state, the legacy store does not — benign crash
#: residue (journal-first), replayable idempotently. Tolerated inside the tail.
CLASS_JOURNAL_AHEAD = "journal-ahead"
#: Legacy store has the entity/state, the journal does not — an unjournaled
#: mutation of record (a C3 completeness violation). A BUG.
CLASS_LEGACY_AHEAD = "legacy-ahead"
#: Both have the entity but with a differing state. A BUG.
CLASS_CONFLICT = "conflict"

SEVERITY_OK = "ok"
SEVERITY_BUG = "bug"

#: The severity each class carries (the classification is mechanical, not
#: narrated — journal-ahead is OK, the other two are bugs).
CLASS_SEVERITY = {
    CLASS_JOURNAL_AHEAD: SEVERITY_OK,
    CLASS_LEGACY_AHEAD: SEVERITY_BUG,
    CLASS_CONFLICT: SEVERITY_BUG,
}

#: Entity kinds the gate classifies.
ENTITY_SESSION = "session"
ENTITY_EFFORT = "effort"

#: The default bounded tail window. 0 = strict (the quiescent gate the
#: healthcheck + the tests run: every dual-write has settled, so nothing is
#: legitimately in flight). A LIVE gate may pass a small margin to tolerate the
#: handful of in-flight dual-writes at the journal tip.
DEFAULT_TAIL_WINDOW = 0

#: The one effort lane the journal reconstructs at job-id granularity (see the
#: module scope note). ``grass`` is the store subdir name.
JOURNAL_EFFORT_LANES = ("grass",)


# ── Journal-derived views ────────────────────────────────────────────────────

def derive_session_view_from_journal(events) -> dict:
    """Replay the session-lifecycle events into ``{sid: {lane,status,seq}}``.

    Events are applied in ``seq`` order (the journal is append-ordered, but we
    sort defensively). ``started`` creates a RUNNING row; ``advanced`` moves the
    lane (status unchanged); ``killed`` → DONE; ``closed`` → IDLE. ``seq`` on
    each derived row is the seq of the LAST event that touched it (for the tail
    window). Unknown-field-tolerant: a payload missing ``session_id`` is skipped.
    """
    from session_registry import (STATUS_RUNNING, STATUS_DONE, STATUS_IDLE)
    view = {}
    for ev in sorted(events, key=lambda e: _seq_of(e)):
        t = ev.get("type")
        payload = ev.get("payload") or {}
        sid = payload.get("session_id")
        if not sid:
            continue
        seq = _seq_of(ev)
        if t == _journal.EV_SESSION_STARTED:
            view[sid] = {"lane": payload.get("lane", "") or "",
                         "status": STATUS_RUNNING, "seq": seq}
        elif t == _journal.EV_SESSION_ADVANCED:
            row = view.get(sid) or {"status": STATUS_RUNNING}
            row = dict(row)
            row["lane"] = payload.get("lane", row.get("lane", "")) or ""
            row["seq"] = seq
            view[sid] = row
        elif t == _journal.EV_SESSION_KILLED:
            row = dict(view.get(sid) or {})
            row.setdefault("lane", payload.get("lane", "") or "")
            row["status"] = STATUS_DONE
            row["seq"] = seq
            view[sid] = row
        elif t == _journal.EV_SESSION_CLOSED:
            row = dict(view.get(sid) or {})
            row.setdefault("lane", payload.get("lane", "") or "")
            row["status"] = STATUS_IDLE
            row["seq"] = seq
            view[sid] = row
    return view


def derive_effort_view_from_journal(events) -> dict:
    """Replay grass effort events into ``{lane: {job_id: seq}}``.

    Grass is the one effort lane the journal carries at job-id granularity:
    ``grass-idea-added`` (payload ``idea_id``) and an inbox ``effort-promoted``
    (payload ``job_id``) ADD a membership; ``grass-idea-deleted`` (payload
    ``idea_id``) REMOVES it; the in-place status/refined/archived/exported events
    are no-ops on membership (the idea keeps its index slot). ``seq`` is the add
    event's seq (for the tail window). Insertion order is preserved (dict
    ordering) so a rebuild can restore the append-only index order.
    """
    grass = {}
    for ev in sorted(events, key=lambda e: _seq_of(e)):
        t = ev.get("type")
        payload = ev.get("payload") or {}
        seq = _seq_of(ev)
        if t == _journal.EV_GRASS_IDEA_ADDED:
            jid = payload.get("idea_id")
            if jid and jid not in grass:
                grass[jid] = seq
        elif t == _journal.EV_EFFORT_PROMOTED:
            # Only the inbox→grass promote adds a grass index entry (it carries a
            # ``job_id``). The grass→lane promote (``idea_id``+``lane``) starts a
            # SESSION + annotates the existing idea — it adds no grass slot.
            jid = payload.get("job_id")
            if jid and jid not in grass:
                grass[jid] = seq
        elif t == _journal.EV_GRASS_IDEA_DELETED:
            jid = payload.get("idea_id")
            grass.pop(jid, None)
    out = {}
    if grass:
        out["grass"] = grass
    return out


def _seq_of(ev) -> int:
    try:
        return int(ev.get("seq", 0))
    except (TypeError, ValueError):
        return 0


# ── Legacy-store-derived views ───────────────────────────────────────────────

def derive_session_view_from_store(project_id) -> dict:
    """The project's session rows as ``{sid: {lane,status}}`` (SAFE projection).

    Reads :mod:`session_registry` (the global ``sessions.json``) filtered to the
    project. Never projects ``worktree_path``/``branch`` — parity compares only
    the lane + status the journal can also derive.
    """
    import session_registry as _reg
    view = {}
    for rec in _reg.list_sessions(project_id=project_id):
        sid = rec.get("session_id")
        if not sid:
            continue
        view[sid] = {"lane": rec.get("lane", "") or "",
                     "status": rec.get("status", "") or ""}
    return view


def derive_effort_view_from_store(folder_path, project_id, lanes=None) -> dict:
    """The project's per-lane ``index.json`` membership as ``{lane: [job_ids]}``.

    Reads the raw ordered index (``effort_history._load_index``) for each lane in
    ``lanes`` (default :data:`JOURNAL_EFFORT_LANES` — the journal-reconstructable
    set). Presence-only: the job-id ORDER is preserved but parity compares the
    membership set (order drift is not a divergence — the append-only index and a
    rebuild agree on membership; a rebuild also restores order).
    """
    import effort_history as _eh
    lanes = tuple(lanes) if lanes is not None else JOURNAL_EFFORT_LANES
    out = {}
    for lane in lanes:
        order = _eh._load_index(folder_path, project_id, lane)
        if order:
            out[lane] = list(order)
    return out


# ── Snapshot (WRITE_LOCK-bracketed consistent read) ──────────────────────────

def resolve_folder(project_id, folder_path=None):
    """Resolve a project's folder (the CLI passes ``None`` → look it up).

    An explicit ``folder_path`` wins (pure, decoupled). Otherwise the project's
    ``folder_path`` is read from :mod:`rnd_registry`; an unresolvable project
    falls back to the data-dir root — matching :func:`journal.journal_path` so
    the journal and the effort stores are read from the same place.
    """
    if folder_path:
        return str(folder_path)
    try:
        import rnd_registry as _rnd
        proj = _rnd.get_project(project_id)
        folder = (proj or {}).get("folder_path", "") or ""
    except Exception:
        folder = ""
    return folder or str(_paths.data_dir())


def snapshot(project_id, folder_path=None, lanes=None) -> dict:
    """Read journal events + legacy stores as ONE consistent snapshot.

    Under :data:`paths.WRITE_LOCK` (so no dual-write can interleave the reads),
    copies the journal events and both legacy stores into memory and returns
    ``{"events", "session_store", "effort_store", "folder_path"}``. Pure —
    mutates nothing.
    """
    lanes = tuple(lanes) if lanes is not None else JOURNAL_EFFORT_LANES
    folder = resolve_folder(project_id, folder_path)
    with _paths.WRITE_LOCK:
        events = _journal.read_events(project_id, folder_path=folder)
        session_store = derive_session_view_from_store(project_id)
        effort_store = derive_effort_view_from_store(
            folder, project_id, lanes=lanes)
    return {"events": events, "session_store": session_store,
            "effort_store": effort_store, "folder_path": folder}


# ── The classifying gate ─────────────────────────────────────────────────────

class ParityReport:
    """The classified journal↔legacy divergence report for one project.

    ``divergences`` is a list of dict rows ``{entity, key, classification,
    severity, detail, seq}``. ``seq`` is set for journal-ahead rows (the seq of
    the journal event that carries the entity) so the tail window can tolerate
    the in-flight tip. Nothing here mutates a store.
    """

    def __init__(self, project_id, divergences, max_seq, tail_window):
        self.project_id = project_id
        self.divergences = list(divergences)
        self.max_seq = int(max_seq)
        self.tail_window = int(tail_window)

    # ── severity helpers ────────────────────────────────────────────────────
    @property
    def bugs(self) -> list:
        """The BUG-severity rows (legacy-ahead + conflict) — never tolerated."""
        return [d for d in self.divergences
                if d.get("severity") == SEVERITY_BUG]

    def _in_tail(self, row) -> bool:
        """True when a journal-ahead row sits inside the bounded tail window."""
        if row.get("classification") != CLASS_JOURNAL_AHEAD:
            return False
        if self.tail_window <= 0:
            return False
        seq = row.get("seq")
        if seq is None:
            return False
        return int(seq) > (self.max_seq - self.tail_window)

    def effective_divergences(self) -> list:
        """Divergences that COUNT — every bug, plus journal-ahead BEYOND the tail.

        A journal-ahead row inside the tail window is a legitimate in-flight
        dual-write and is tolerated (not counted).
        """
        out = []
        for d in self.divergences:
            if d.get("classification") == CLASS_JOURNAL_AHEAD and self._in_tail(d):
                continue
            out.append(d)
        return out

    def is_clean(self) -> bool:
        """Zero divergence, bounded-tail-tolerant (no bug, no beyond-tail ahead)."""
        return not self.effective_divergences()

    def classification_counts(self) -> dict:
        counts = {CLASS_JOURNAL_AHEAD: 0, CLASS_LEGACY_AHEAD: 0,
                  CLASS_CONFLICT: 0}
        for d in self.divergences:
            c = d.get("classification")
            if c in counts:
                counts[c] += 1
        return counts

    def summary(self) -> str:
        c = self.classification_counts()
        eff = len(self.effective_divergences())
        return (f"parity[{self.project_id}]: {'CLEAN' if self.is_clean() else 'DIVERGENT'} "
                f"— effective={eff} bugs={len(self.bugs)} "
                f"journal-ahead={c[CLASS_JOURNAL_AHEAD]} "
                f"legacy-ahead={c[CLASS_LEGACY_AHEAD]} "
                f"conflict={c[CLASS_CONFLICT]} "
                f"(tail_window={self.tail_window}, max_seq={self.max_seq})")


def _classify_map(entity, journal_map, store_map, journal_seq):
    """Classify one entity's journal-view vs store-view maps into rows.

    ``journal_map`` / ``store_map`` are ``{key: state}`` (state may be a dict of
    fields to compare, or ``None`` for presence-only membership). ``journal_seq``
    maps a key → the seq of the journal event that carries it (for the tail).
    """
    rows = []
    keys = set(journal_map) | set(store_map)
    for key in sorted(keys, key=lambda k: str(k)):
        in_j = key in journal_map
        in_s = key in store_map
        if in_j and in_s:
            jstate = journal_map[key]
            sstate = store_map[key]
            if jstate is not None and sstate is not None and jstate != sstate:
                rows.append({
                    "entity": entity, "key": key,
                    "classification": CLASS_CONFLICT,
                    "severity": CLASS_SEVERITY[CLASS_CONFLICT],
                    "detail": f"journal={jstate} store={sstate}",
                    "seq": journal_seq.get(key),
                })
            # else: parity — no row.
        elif in_j and not in_s:
            rows.append({
                "entity": entity, "key": key,
                "classification": CLASS_JOURNAL_AHEAD,
                "severity": CLASS_SEVERITY[CLASS_JOURNAL_AHEAD],
                "detail": "in journal, absent from legacy store",
                "seq": journal_seq.get(key),
            })
        else:  # in_s and not in_j
            rows.append({
                "entity": entity, "key": key,
                "classification": CLASS_LEGACY_AHEAD,
                "severity": CLASS_SEVERITY[CLASS_LEGACY_AHEAD],
                "detail": "in legacy store, absent from journal",
                "seq": None,
            })
    return rows


def classify_parity(project_id, folder_path=None, lanes=None,
                    tail_window=DEFAULT_TAIL_WINDOW) -> ParityReport:
    """Classify a project's journal↔legacy divergence — the parity gate.

    Snapshots the journal + both legacy stores under :data:`paths.WRITE_LOCK`,
    derives the session + effort views from each, and classifies every
    divergence (journal-ahead / legacy-ahead / conflict). Returns a
    :class:`ParityReport`. Mutates nothing.
    """
    snap = snapshot(project_id, folder_path=folder_path, lanes=lanes)
    events = snap["events"]
    max_seq = max((_seq_of(e) for e in events), default=0)

    # Session entity: compare {lane,status}.
    j_sessions = derive_session_view_from_journal(events)
    s_sessions = snap["session_store"]
    j_sess_map = {sid: {"lane": v.get("lane", ""), "status": v.get("status", "")}
                  for sid, v in j_sessions.items()}
    j_sess_seq = {sid: v.get("seq") for sid, v in j_sessions.items()}
    s_sess_map = {sid: {"lane": v.get("lane", ""), "status": v.get("status", "")}
                  for sid, v in s_sessions.items()}
    rows = _classify_map(ENTITY_SESSION, j_sess_map, s_sess_map, j_sess_seq)

    # Effort entity: grass index membership (presence-only, per lane).
    j_effort = derive_effort_view_from_journal(events)
    s_effort = snap["effort_store"]
    effort_lanes = set(j_effort) | set(s_effort)
    for lane in sorted(effort_lanes):
        j_ids = j_effort.get(lane, {})  # {job_id: seq}
        s_ids = {jid: None for jid in s_effort.get(lane, [])}
        j_map = {jid: None for jid in j_ids}
        j_seq = dict(j_ids)
        lane_rows = _classify_map(ENTITY_EFFORT, j_map, s_ids, j_seq)
        for r in lane_rows:
            r["lane"] = lane
            r["key"] = f"{lane}/{r['key']}"
        rows.extend(lane_rows)

    return ParityReport(project_id, rows, max_seq, tail_window)
