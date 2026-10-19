"""Write-site tripwire for the C3 event-log spine (W1).

A test-mode wrapper around Python-level file writes that lands under any
``.anchor/`` directory. Two jobs, two modes:

* **inventory mode** (W1, now): run across the full test suite + the (stubbed)
  healthcheck via the ``ANCHOR_WRITE_TRIPWIRE`` env seam, it records every
  write site (product ``module:function``) together with the NORMALIZED store
  path it mutated — the mechanical mutation-of-record inventory the C3
  instrumentation waves consume. Never raises, never alters behavior.
* **enforce mode** (the permanent C3 completeness gate — FLIPPED ON in W13, now
  the real gate, on forever): any mutation of a ``.anchor/`` store that is NOT
  paired with a journal event (see :func:`journal_event`) raises
  :class:`TripwireViolation` naming the write site. The journal path itself is
  allowlisted — journal appends never need pairing. The blessed wrappers
  (:class:`journal.journaled` / :func:`journal.dual_write`) pair every
  instrumented mutation-of-record; :class:`journal.completeness_gate` arms this
  mode + the journal flag together (used by the W13 test + the healthcheck's
  completeness walk). Armed via ``ANCHOR_WRITE_TRIPWIRE=enforce`` (the
  orchestrator/healthcheck seam) or programmatically by ``completeness_gate``.

Interception points (writes only; reads pass through untouched):
``builtins.open`` / ``io.open`` with a write/append/create mode (this also
covers ``pathlib.Path.write_text``/``write_bytes``/``open``, which route
through ``io.open``), ``os.replace`` / ``os.rename`` (the atomic tmp→target
idiom every Anchor store uses), and ``os.remove`` / ``os.unlink`` (record
deletion is a mutation of record too). Writes whose path has no ``.anchor``
component are ignored. Wrappers are exception-safe: any tripwire-internal
error falls back to the original call in inventory mode.

Stdlib only; install/uninstall is idempotent and restores the originals.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import re
import sys
import threading
from pathlib import Path, PurePath

REPO_ROOT = Path(__file__).resolve().parent.parent
_SELF_FILE = str(Path(__file__).resolve())

MODE_INVENTORY = "inventory"
MODE_ENFORCE = "enforce"

# Journal allowlist (the journal lands in W12; the names are fixed NOW so the
# tripwire contract is complete before the journal exists). A path is journal
# when its final component is a journal file, or any directory component is
# the ``journal`` dir.
JOURNAL_FILENAMES = ("journal.jsonl",)
JOURNAL_DIRNAMES = ("journal",)

DEFAULT_INVENTORY_PATH = (
    REPO_ROOT / "planning" / "rearch-2026-07" / "MUTATION-INVENTORY.json"
)

_WRITE_MODE_CHARS = ("w", "a", "x", "+")

_LOCK = threading.Lock()
_TLS = threading.local()

_STATE = {
    "installed": False,
    "mode": MODE_INVENTORY,
    # (store, op, site) -> count
    "records": {},
    "originals": {},
}


class TripwireViolation(RuntimeError):
    """A ``.anchor/`` store was mutated without a paired journal event
    (enforce mode only)."""


# ── path classification ─────────────────────────────────────────────────────

_HEX_ID_RE = re.compile(r"[0-9a-fA-F]{8,}")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_PREFIX_ID_RE = re.compile(
    r"(idea|grass|dev|run|disc|job|entry|session|build|effort)[-_].+",
    re.IGNORECASE,
)


def _normalize_component(comp):
    """Normalize one path component to a stable inventory class token."""
    c = comp
    if c.endswith(".tmp"):  # the atomic-write tmp twin folds onto its target
        c = c[:-4]
    stem, dot, ext = c.rpartition(".")
    body = stem if dot else c
    suffix = (dot + ext) if dot else ""
    if _UUID_RE.fullmatch(body) or _HEX_ID_RE.fullmatch(body):
        return "<id>" + suffix
    if body.isdigit():
        return "<n>" + suffix
    m = _PREFIX_ID_RE.fullmatch(body)
    if m:
        return m.group(1).lower() + "-<id>" + suffix
    return c


def classify_store_path(path):
    """Normalize a path under ``.anchor/`` to its store class, or None.

    ``…/.anchor/projects/3f2a…9c/planning/index.json.tmp`` →
    ``.anchor/projects/<id>/planning/index.json``. Returns None for a path
    with no ``.anchor`` component (not a store — ignored).
    """
    try:
        parts = PurePath(os.fspath(path)).parts
    except TypeError:
        return None
    idx = None
    for i, part in enumerate(parts):
        if part == ".anchor":
            idx = i
    if idx is None:
        return None
    rel = [_normalize_component(p) for p in parts[idx + 1:]]
    return "/".join([".anchor"] + rel)


def is_journal_path(path):
    """True when the path is the (allowlisted) journal itself."""
    try:
        parts = PurePath(os.fspath(path)).parts
    except TypeError:
        return False
    if not parts:
        return False
    name = parts[-1]
    if name.endswith(".tmp"):
        name = name[:-4]
    if name in JOURNAL_FILENAMES:
        return True
    return any(p in JOURNAL_DIRNAMES for p in parts[:-1])


# ── write-site resolution ───────────────────────────────────────────────────

def _find_site():
    """Walk the stack to the first PRODUCT frame (repo, non-test, non-self).

    Falls back to the first repo test frame (honest: some mutations happen
    directly in test/healthcheck code), then to ``<external>``. Site format is
    ``relpath:function`` — deliberately line-number-free so the checked-in
    inventory stays stable across unrelated edits.
    """
    f = sys._getframe(1)
    fallback = None
    while f is not None:
        fn = f.f_code.co_filename
        if fn != _SELF_FILE and not fn.startswith("<"):
            try:
                rel = str(Path(fn).resolve().relative_to(REPO_ROOT))
            except (ValueError, OSError):
                rel = None
            if rel is not None:
                rel = rel.replace("\\", "/")
                site = f"{rel}:{f.f_code.co_name}"
                is_test = rel.startswith("tests/") or "conftest" in rel
                if not is_test:
                    return site
                if fallback is None:
                    fallback = site
        f = f.f_back
    return fallback or "<external>"


# ── the choke point ─────────────────────────────────────────────────────────

def journal_event():
    """Context manager arming the journal pairing for the enclosed writes.

    The future ``journal.emit()`` (W12) wraps its journal-first-then-legacy
    sequence in this, so the blessed legacy-store writes it triggers are
    PAIRED. Nestable; thread-local.
    """
    class _Armed:
        def __enter__(self):
            _TLS.journal_armed = getattr(_TLS, "journal_armed", 0) + 1
            return self

        def __exit__(self, *exc):
            _TLS.journal_armed = max(
                0, getattr(_TLS, "journal_armed", 0) - 1)
            return False

    return _Armed()


def mark_journal_event():
    """Imperative arm (see :func:`journal_event`); pair with
    :func:`clear_journal_event`."""
    _TLS.journal_armed = getattr(_TLS, "journal_armed", 0) + 1


def clear_journal_event():
    _TLS.journal_armed = max(0, getattr(_TLS, "journal_armed", 0) - 1)


def _record(op, path):
    """Record (and in enforce mode, police) one write under ``.anchor/``.

    Inventory mode NEVER raises — any internal error is swallowed so the
    tripwire can run across the whole suite without changing behavior.
    Enforce mode raises :class:`TripwireViolation` on an unpaired mutation.
    """
    if getattr(_TLS, "in_hook", False):
        return
    _TLS.in_hook = True
    try:
        store = classify_store_path(path)
        if store is None:
            return
        site = _find_site()
        with _LOCK:
            key = (store, op, site)
            _STATE["records"][key] = _STATE["records"].get(key, 0) + 1
        if _STATE["mode"] == MODE_ENFORCE:
            if is_journal_path(path):
                return  # the journal itself is allowlisted
            if getattr(_TLS, "journal_armed", 0) > 0:
                return  # paired with a journal event
            raise TripwireViolation(
                f"unjournaled mutation of record: {op} on '{store}' at "
                f"{site} — every .anchor/ mutation must be paired with a "
                f"journal event (tools.write_tripwire.journal_event)."
            )
    except TripwireViolation:
        raise
    except Exception:
        if _STATE["mode"] == MODE_ENFORCE:
            raise
        # inventory mode: never let tripwire internals break a write
    finally:
        _TLS.in_hook = False


def _is_write_mode(mode):
    return any(ch in mode for ch in _WRITE_MODE_CHARS)


def _make_open_wrapper(orig_open):
    def tripwire_open(file, mode="r", *args, **kwargs):
        try:
            watchable = isinstance(file, (str, bytes, os.PathLike))
            if watchable and _is_write_mode(str(mode)):
                _record("write", file)
        except TripwireViolation:
            raise
        except Exception:
            pass
        return orig_open(file, mode, *args, **kwargs)

    tripwire_open._anchor_tripwire = True
    return tripwire_open


def _make_dst_wrapper(orig_fn, op):
    def tripwire_move(src, dst, *args, **kwargs):
        try:
            _record(op, dst)
        except TripwireViolation:
            raise
        except Exception:
            pass
        return orig_fn(src, dst, *args, **kwargs)

    tripwire_move._anchor_tripwire = True
    return tripwire_move


def _make_path_wrapper(orig_fn, op):
    def tripwire_unlink(path, *args, **kwargs):
        try:
            _record(op, path)
        except TripwireViolation:
            raise
        except Exception:
            pass
        return orig_fn(path, *args, **kwargs)

    tripwire_unlink._anchor_tripwire = True
    return tripwire_unlink


# ── install / uninstall / query ─────────────────────────────────────────────

def install(mode=MODE_INVENTORY, clear=True):
    """Install the tripwire process-wide. Idempotent (re-install just
    switches mode)."""
    if mode not in (MODE_INVENTORY, MODE_ENFORCE):
        raise ValueError(f"unknown tripwire mode: {mode!r}")
    with _LOCK:
        if clear:
            _STATE["records"] = {}
        _STATE["mode"] = mode
        if _STATE["installed"]:
            return
        _STATE["originals"] = {
            "builtins.open": builtins.open,
            "io.open": io.open,
            "os.replace": os.replace,
            "os.rename": os.rename,
            "os.remove": os.remove,
            "os.unlink": os.unlink,
        }
        builtins.open = _make_open_wrapper(_STATE["originals"]["builtins.open"])
        io.open = _make_open_wrapper(_STATE["originals"]["io.open"])
        os.replace = _make_dst_wrapper(_STATE["originals"]["os.replace"],
                                       "replace")
        os.rename = _make_dst_wrapper(_STATE["originals"]["os.rename"],
                                      "rename")
        os.remove = _make_path_wrapper(_STATE["originals"]["os.remove"],
                                       "remove")
        os.unlink = _make_path_wrapper(_STATE["originals"]["os.unlink"],
                                       "remove")
        _STATE["installed"] = True


def uninstall():
    """Restore every patched original. Idempotent."""
    with _LOCK:
        if not _STATE["installed"]:
            return
        o = _STATE["originals"]
        builtins.open = o["builtins.open"]
        io.open = o["io.open"]
        os.replace = o["os.replace"]
        os.rename = o["os.rename"]
        os.remove = o["os.remove"]
        os.unlink = o["os.unlink"]
        _STATE["originals"] = {}
        _STATE["installed"] = False


def is_installed():
    return _STATE["installed"]


def current_mode():
    return _STATE["mode"]


def active(mode=MODE_INVENTORY, clear=True):
    """Context manager: install on enter, uninstall on exit."""
    class _Active:
        def __enter__(self):
            install(mode=mode, clear=clear)
            return sys.modules[__name__]

        def __exit__(self, *exc):
            uninstall()
            return False

    return _Active()


def inventory():
    """The recorded mutation-of-record inventory, deterministically sorted.

    Returns ``[{"store", "op", "site", "count"}, …]`` sorted by
    (store, site, op).
    """
    with _LOCK:
        items = [
            {"store": store, "op": op, "site": site, "count": count}
            for (store, op, site), count in _STATE["records"].items()
        ]
    items.sort(key=lambda r: (r["store"], r["site"], r["op"]))
    return items


def clear_inventory():
    with _LOCK:
        _STATE["records"] = {}


def write_inventory(path=None, merge=True):
    """Write the inventory artifact (JSON). With ``merge=True`` (default) an
    existing artifact's entries are folded in (counts summed), so the full
    suite and the healthcheck ACCUMULATE into one checked-in inventory.

    Returns the path written. Never intercepted by the tripwire itself (the
    artifact lives outside ``.anchor/``; the reentrancy guard covers the rest).
    """
    target = Path(path) if path is not None else DEFAULT_INVENTORY_PATH
    entries = {(r["store"], r["op"], r["site"]): r["count"]
               for r in inventory()}
    if merge and target.exists():
        try:
            prior = json.loads(target.read_text(encoding="utf-8"))
            for r in prior.get("entries", []):
                key = (r["store"], r["op"], r["site"])
                entries[key] = entries.get(key, 0) + int(r.get("count", 0))
        except Exception:
            pass  # a torn/hand-mangled prior artifact never blocks the write
    merged = [
        {"store": store, "op": op, "site": site, "count": count}
        for (store, op, site), count in entries.items()
    ]
    merged.sort(key=lambda r: (r["store"], r["site"], r["op"]))
    payload = {
        "artifact": "mutation-of-record inventory (W1 write-site tripwire)",
        "generator": "tools/write_tripwire.py",
        "journal_allowlist": {
            "filenames": list(JOURNAL_FILENAMES),
            "dirnames": list(JOURNAL_DIRNAMES),
        },
        "entries": merged,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(str(tmp), str(target))
    return target


def env_requested_mode(environ=None):
    """The mode requested via ``ANCHOR_WRITE_TRIPWIRE``, or None.

    ``1``/``inventory`` → inventory; ``enforce`` → enforce; anything else
    (including unset/blank) → None. The env seam is how the orchestrator runs
    the FULL suite + healthcheck under the tripwire without touching any test.
    """
    env = os.environ if environ is None else environ
    raw = (env.get("ANCHOR_WRITE_TRIPWIRE") or "").strip().lower()
    if raw in ("1", "inventory", "true", "on"):
        return MODE_INVENTORY
    if raw == "enforce":
        return MODE_ENFORCE
    return None
