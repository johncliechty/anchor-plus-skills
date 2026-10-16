"""Chamber-local event-time projections (steward-chamber W4, Phase-1 substrate).

The deterministic data substrate the 2-second Seal open reads. This module
owns the CHAMBER SIDECAR projection store — append-only, event-time records of
what the chamber itself observed:

    commission_start      — a commission was confirmed and its session launched
    step_yield            — a produced run landed its one-line yield on a step
    deliverable_landing   — the manifest-declared deliverable appeared on disk
    run_death             — a commissioned run died (or timed out) under watch

THE DERIVED-DATA LAW (the plan's words): projections are REBUILDABLE derived
data, never source of truth. The engine spine — ``roadmap.json`` (whose
``roadmap_events`` has exactly ONE writer: Ecgberht ``engine/roadmap.mjs ::
appendRoadmapEvent / appendRoadmapEventDurable``), the ``.ecgberht/`` receipt
and reflection stores — is NEVER written by this module. Everything here lives
under the project's ``.anchor/chamber/`` sidecar; deleting the store loses
nothing that cannot be re-derived (the W5 cold-open rebuild).

DURABILITY (property gate, hardening law 0080):

* **Atomic write** — every snapshot lands via temp + fsync + rename
  (``os.replace``). A writer killed mid-write leaves the PRIOR snapshot
  readable; the temp file is orphaned junk, never the store. The
  ``ANCHOR_CHAMBER_KILL_POINT`` env seam lets the W4 crash test kill a REAL
  process at the two dangerous instants (mid-temp-write / before-rename).
* **Single-writer serialization** — appends are serialized by a CROSS-PROCESS
  kernel lock (``msvcrt.locking`` on Windows, ``fcntl.flock`` elsewhere) on
  ``projections.lock`` beside the store. The kernel releases the lock when the
  holding process dies, so a killed writer can never wedge the store — no
  stale-lock heuristics, no lock-age guesswork. See :data:`SINGLE_WRITER`.
* **No event dropped** — an append is read-snapshot → append → atomic-rewrite
  UNDER the lock, so two real processes appending concurrently interleave
  whole events, never lose one (the W4 two-real-process concurrency test).

READERS NEVER WRITE. The open path calls :func:`projection_view` (one read);
a missing store is honestly empty; a CORRUPT store raises the named
:class:`ProjectionStoreError` (``projection-store-unreadable``) — the W5/W6
degraded-rail state, never a silent empty and never a clobbering "repair".

Stdlib only.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

SCHEMA = "anchor-chamber-projections-v1"

#: Sidecar layout, relative to the PROJECT folder (never an absolute path).
CHAMBER_SIDECAR_REL = os.path.join(".anchor", "chamber")
PROJECTIONS_REL = os.path.join(CHAMBER_SIDECAR_REL, "projections.json")
PROJECTIONS_LOCK_REL = os.path.join(CHAMBER_SIDECAR_REL, "projections.lock")

#: The four event-time projection kinds the chamber records (W4 contract).
KIND_COMMISSION_START = "commission_start"
KIND_STEP_YIELD = "step_yield"
KIND_DELIVERABLE_LANDING = "deliverable_landing"
KIND_RUN_DEATH = "run_death"
PROJECTION_EVENT_KINDS = (
    KIND_COMMISSION_START,
    KIND_STEP_YIELD,
    KIND_DELIVERABLE_LANDING,
    KIND_RUN_DEATH,
)

#: Reserved envelope keys — an event's caller fields may not shadow them.
RESERVED_EVENT_KEYS = ("seq", "kind", "at")

#: The documented single-writer serialization (the durability property gate
#: demands the serialization be DOCUMENTED, not just present). Machine-readable
#: so tests and later waves can assert the law rather than trust prose.
SINGLE_WRITER = {
    "store": PROJECTIONS_REL,
    "lock": PROJECTIONS_LOCK_REL,
    "mechanism": "kernel file lock (msvcrt.locking on Windows, fcntl.flock "
                 "elsewhere) held for the whole read-append-rewrite cycle",
    "atomic_write": "temp + fsync + os.replace",
    "auto_release": "the kernel releases the lock on process death — a killed "
                    "writer never wedges the store",
    "law": "ALL appends go through chamber_projections.append_event; the store "
           "is rebuildable derived data (never source of truth); the engine "
           "spine (roadmap_events single writer engine/roadmap.mjs, .ecgberht "
           "receipts/reflections) is never written by chamber code",
}

#: Test seam: kill a REAL writer process at a named point inside the atomic
#: write (the W4 kill-during-write crash test). Never set in production.
KILL_POINT_ENV = "ANCHOR_CHAMBER_KILL_POINT"
KILL_MID_TEMP = "mid-temp-write"
KILL_BEFORE_RENAME = "before-rename"

#: How long an append waits for the cross-process lock before refusing.
LOCK_TIMEOUT_S = 15.0

ERROR_STORE_UNREADABLE = "projection-store-unreadable"
ERROR_LOCK_TIMEOUT = "projection-lock-timeout"
ERROR_UNKNOWN_KIND = "unknown-projection-kind"


class ProjectionStoreError(RuntimeError):
    """Named projection-store failure. ``.error`` carries the named state
    (``projection-store-unreadable`` | ``projection-lock-timeout`` |
    ``unknown-projection-kind``)."""

    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error = error


# ── Paths ────────────────────────────────────────────────────────────────────

def store_path(folder) -> Path:
    return Path(folder) / PROJECTIONS_REL


def lock_path(folder) -> Path:
    return Path(folder) / PROJECTIONS_LOCK_REL


# ── Cross-process lock (kernel-managed; auto-released on process death) ─────

class _FileLock:
    """Exclusive cross-process lock on a dedicated lock file.

    Kernel-managed byte-range/flock lock: released automatically when the
    holding process exits OR is killed, which is exactly why it is used here —
    the kill-during-write crash test leaves no lock to break.
    """

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_S):
        self._path = Path(path)
        self._timeout = timeout
        self._fd = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise ProjectionStoreError(
                        ERROR_LOCK_TIMEOUT,
                        "could not acquire %s within %.0fs — another writer "
                        "holds the projection lock" % (self._path, self._timeout))
                time.sleep(0.01)

    def __exit__(self, *exc):
        fd, self._fd = self._fd, None
        if fd is None:
            return False
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
        return False


def file_lock(path, timeout: float = LOCK_TIMEOUT_S) -> _FileLock:
    """Public lock helper — chamber sidecar stores (manifest hash record etc.)
    share the same serialization discipline instead of growing their own."""
    return _FileLock(Path(path), timeout)


# ── Atomic write (temp + fsync + rename) ─────────────────────────────────────

def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    kill = os.environ.get(KILL_POINT_ENV, "")
    try:
        if kill == KILL_MID_TEMP:
            os.write(fd, data[: max(1, len(data) // 2)])
            os.fsync(fd)
            os._exit(9)
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = None
        if kill == KILL_BEFORE_RENAME:
            os._exit(9)
        os.replace(tmp_name, target)
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(target, obj) -> None:
    """Public temp + fsync + rename JSON write (the sidecar-wide discipline)."""
    _atomic_write_bytes(Path(target),
                        json.dumps(obj, indent=2).encode("utf-8"))


def _sweep_stale_tmp(target: Path, max_age_s: float = 3600.0) -> None:
    """Best-effort: drop orphaned temp files a killed writer left behind.
    Only our own prefix, only stale ones — never the store."""
    try:
        now = time.time()
        for p in target.parent.glob(target.name + ".*.tmp"):
            try:
                if now - p.stat().st_mtime > max_age_s:
                    p.unlink()
            except OSError:
                pass
    except OSError:
        pass


# ── Load / read (readers never write) ────────────────────────────────────────

def _empty_store() -> dict:
    return {"schema": SCHEMA, "events": []}


def load_store(folder) -> dict:
    """The raw store document. Missing → honestly empty. Corrupt → the named
    ``projection-store-unreadable`` error, NEVER a silent empty (a reader that
    invents emptiness would hide data loss; the W5 rebuild is the cure)."""
    p = store_path(folder)
    if not p.exists():
        return _empty_store()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("events"), list):
            raise ValueError("projection store is not a {schema, events} doc")
        return doc
    except (ValueError, OSError) as exc:
        raise ProjectionStoreError(
            ERROR_STORE_UNREADABLE,
            "chamber projection store unreadable (%s): %s — rebuildable "
            "derived data; the W5 cold-open rebuild re-derives it"
            % (PROJECTIONS_REL, exc))


def read_events(folder, kinds=None) -> list:
    """Events in append order, optionally filtered to ``kinds``."""
    events = load_store(folder)["events"]
    if kinds is None:
        return list(events)
    want = set(kinds)
    return [e for e in events if e.get("kind") in want]


def latest(folder, kind) -> dict | None:
    """The most recent event of ``kind`` (None when none landed)."""
    hits = read_events(folder, kinds=(kind,))
    return hits[-1] if hits else None


def projection_view(folder) -> dict:
    """The open-path read: ONE store read → everything the paint needs.
    Never writes, never spawns, never touches the spine."""
    store = load_store(folder)
    events = store["events"]
    counts = {k: 0 for k in PROJECTION_EVENT_KINDS}
    for e in events:
        k = e.get("kind")
        if k in counts:
            counts[k] += 1
    return {
        "schema": store.get("schema"),
        "events": list(events),
        "counts": counts,
        "last_seq": events[-1]["seq"] if events else 0,
    }


# ── Append (the single serialized writer path) ───────────────────────────────

def append_event(folder, kind: str, fields: dict | None = None) -> dict:
    """Append ONE event. The only write path to the store — serialized by the
    cross-process lock, landed atomically. Returns the appended event."""
    if kind not in PROJECTION_EVENT_KINDS:
        raise ProjectionStoreError(
            ERROR_UNKNOWN_KIND,
            "unknown projection kind %r (kinds: %s)"
            % (kind, ", ".join(PROJECTION_EVENT_KINDS)))
    fields = dict(fields or {})
    for key in RESERVED_EVENT_KEYS:
        if key in fields:
            raise ProjectionStoreError(
                ERROR_UNKNOWN_KIND,
                "event field %r shadows a reserved envelope key" % key)

    target = store_path(folder)
    with file_lock(lock_path(folder)):
        store = load_store(folder)
        events = store["events"]
        event = {
            "seq": (events[-1]["seq"] if events else 0) + 1,
            "kind": kind,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **fields,
        }
        events.append(event)
        _sweep_stale_tmp(target)
        _atomic_write_bytes(
            target, json.dumps(store, indent=2).encode("utf-8"))
    return event


# ── The four writers (W4 contract) ───────────────────────────────────────────

def record_commission_start(folder, commission_id, *, session_id=None,
                            step_id=None, skill=None, lane=None) -> dict:
    return append_event(folder, KIND_COMMISSION_START, {
        "commission_id": commission_id, "session_id": session_id,
        "step_id": step_id, "skill": skill, "lane": lane})


def record_step_yield(folder, commission_id, step_id, yield_line, *,
                      report_link=None, session_id=None) -> dict:
    return append_event(folder, KIND_STEP_YIELD, {
        "commission_id": commission_id, "step_id": step_id,
        "yield": str(yield_line or "")[:300],
        "report_link": report_link, "session_id": session_id})


def record_deliverable_landing(folder, commission_id, output_path, *,
                               deliverable_type=None, session_id=None) -> dict:
    return append_event(folder, KIND_DELIVERABLE_LANDING, {
        "commission_id": commission_id, "output_path": output_path,
        "deliverable_type": deliverable_type, "session_id": session_id})


def record_run_death(folder, commission_id, *, session_id=None,
                     outcome="died", detail=None) -> dict:
    return append_event(folder, KIND_RUN_DEATH, {
        "commission_id": commission_id, "session_id": session_id,
        "outcome": outcome, "detail": (str(detail)[:300] if detail else None)})


# ── Real-process CLI (the W4 crash + concurrency tests spawn THIS) ──────────

def _cli(argv) -> int:
    """``python chamber_projections.py append-batch <folder> <kind> <count>
    <marker>`` — appends ``count`` events tagged {"marker": marker, "n": i}.
    Exists so the durability tests exercise REAL processes (not threads) with
    trivial, quoting-safe command lines; honors ANCHOR_CHAMBER_KILL_POINT."""
    if len(argv) != 5 or argv[0] != "append-batch":
        print("usage: chamber_projections.py append-batch "
              "<folder> <kind> <count> <marker>")
        return 2
    _, folder, kind, count, marker = argv
    for i in range(int(count)):
        append_event(folder, kind, {"marker": marker, "n": i})
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
