"""Failure-state table validator + STATE-VOCABULARY-MAP loader — W8.

Validates each wave's failure-state table against
``artifacts/STATE-VOCABULARY-MAP.md`` and **fails** the wave when:

* a required hardening row is missing (e.g. ``backing-store-unreadable``)
* any row uses a term absent from the map
* unknown and empty are not SEPARATE rows
* a row omits the user-visible string or its trigger
* a user-facing table names index / rebuild / reconcile instead of the
  surface's own actions (honesty theater — not a style note)

Usage::

    from tests.conformance.table_validator import (
        load_vocabulary_map,
        validate_failure_state_table,
    )

    validate_failure_state_table(table, surface="doctor")
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from anchor.ui.named_state import (
    FORBIDDEN_ROW_MERGES,
    NamedState,
    REQUIRED_SEPARATE_STATES,
    validate_failure_state_table as _w6_validate_merges,
)
from anchor.ui.named_state import FailureStateTableError as W6FailureStateTableError

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SCHEMA = "state-vocabulary-map/v1"
MAP_RELPATH = os.path.join("artifacts", "STATE-VOCABULARY-MAP.md")

HARDENING_TERMS: Tuple[str, ...] = (
    "dependency-missing",
    "dependency-slow-or-killed",
    "dependency-returns-garbage",
    "backing-store-unreadable",
    "empty-but-valid",
)

#: NamedState tokens that must appear exactly once on the map's right side.
NAMED_STATE_TERMS: Tuple[str, ...] = tuple(s.value for s in NamedState)

#: Verbs allowed on user-facing surface tables.
SURFACE_NATIVE_ACTIONS: frozenset = frozenset(
    {
        "open",
        "run",
        "attach",
        "diagnose",
        "preview",
        "restart",
        "tile render",
        "tile_render",
        "render",
        "retry",
        "stop",
        "session",
        "cost",
        "usage",
        "cadence",
        "collapse",
        "summary",
    }
)

#: Honesty-theater verbs — fail (not style) on user-facing tiles.
HONESTY_THEATER_VERBS: frozenset = frozenset({"index", "rebuild", "reconcile"})

#: Surfaces that may legitimately speak index/rebuild/reconcile.
INDEX_BEARING_SURFACES: frozenset = frozenset(
    {
        "index",
        "index-bearing",
        "discovery",
        "brownfield_scan",
        "registry",
    }
)

_VOCAB_BLOCK_RE = re.compile(
    r"```vocab-map\s*(.*?)\s*```",
    re.IGNORECASE | re.DOTALL,
)
_ROW_FIELDS = ("state", "named_state", "hardening", "hardening_term", "term", "name", "id", "code")


class VocabularyMapError(ValueError):
    """STATE-VOCABULARY-MAP.md is missing, unreadable, or not a bijection."""


class TableValidationError(ValueError):
    """A failure-state table is incomplete, unmapped, or honesty theater."""


class HonestyTheaterError(TableValidationError):
    """User-facing table used index/rebuild/reconcile language."""


# --------------------------------------------------------------------------
# Vocabulary map
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VocabularyMap:
    """Parsed bijection: hardening term → frozenset of NamedState tokens."""

    schema: str
    hardening_to_named: Dict[str, frozenset]
    named_to_hardening: Dict[str, str]
    path: str = MAP_RELPATH

    @property
    def hardening_terms(self) -> frozenset:
        return frozenset(self.hardening_to_named.keys())

    @property
    def named_state_terms(self) -> frozenset:
        return frozenset(self.named_to_hardening.keys())

    def resolve_named(self, token: str) -> Optional[str]:
        """Return the hardening term for a NamedState token, if mapped."""
        key = _norm_token(token)
        return self.named_to_hardening.get(key)

    def resolve_hardening(self, token: str) -> Optional[frozenset]:
        key = _norm_hardening(token)
        return self.hardening_to_named.get(key)

    def is_known_term(self, token: str) -> bool:
        key = _norm_token(token)
        hkey = _norm_hardening(token)
        return key in self.named_to_hardening or hkey in self.hardening_to_named


def _norm_token(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, NamedState):
        return raw.value
    return str(raw).strip().lower().replace("-", "_").replace(" ", "_")


def _norm_hardening(raw: Any) -> str:
    if raw is None:
        return ""
    # Hardening terms use hyphens in the plan vocabulary.
    text = str(raw).strip().lower().replace("_", "-").replace(" ", "-")
    # collapse multiple hyphens
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _containment_root() -> Path:
    try:
        from tools import containment_smoke  # type: ignore

        return Path(containment_smoke.containment_root())
    except Exception:
        # tests/conformance/table_validator.py → parents[2] = stage2 root
        return Path(__file__).resolve().parents[2]


def map_path(root: Optional[Path] = None) -> Path:
    base = Path(root) if root is not None else _containment_root()
    return base / MAP_RELPATH


def parse_vocabulary_map_text(text: str, *, path: str = MAP_RELPATH) -> VocabularyMap:
    """Parse the fenced ``vocab-map`` block into a VocabularyMap.

    Enforces: every HARDENING_TERMS member appears exactly once; every
    NAMED_STATE_TERMS member appears exactly once; no foreign terms.
    """
    if not text or not str(text).strip():
        raise VocabularyMapError("STATE-VOCABULARY-MAP is empty: %s" % path)

    m = _VOCAB_BLOCK_RE.search(text)
    if not m:
        raise VocabularyMapError(
            "STATE-VOCABULARY-MAP missing ```vocab-map fenced block: %s" % path
        )
    body = m.group(1)
    schema = SCHEMA
    hardening_to_named: Dict[str, Set[str]] = {}
    named_to_hardening: Dict[str, str] = {}

    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("schema:"):
            schema = line.split(":", 1)[1].strip()
            continue
        if ":" not in line:
            raise VocabularyMapError(
                "vocab-map line has no ':' separator: %r in %s" % (line, path)
            )
        left, right = line.split(":", 1)
        hterm = _norm_hardening(left)
        if not hterm:
            raise VocabularyMapError("blank hardening term in %s" % path)
        named_list = [
            _norm_token(p) for p in re.split(r"[,\s]+", right.strip()) if p.strip()
        ]
        if not named_list:
            raise VocabularyMapError(
                "hardening term %r maps to no NamedState in %s" % (hterm, path)
            )
        if hterm in hardening_to_named:
            raise VocabularyMapError(
                "hardening term %r appears more than once in %s" % (hterm, path)
            )
        named_set: Set[str] = set()
        for n in named_list:
            if not n:
                continue
            if n in named_to_hardening:
                raise VocabularyMapError(
                    "NamedState term %r appears more than once in %s" % (n, path)
                )
            named_to_hardening[n] = hterm
            named_set.add(n)
        hardening_to_named[hterm] = named_set

    # Bijection completeness: every term on both sides exactly once.
    expected_h = {_norm_hardening(t) for t in HARDENING_TERMS}
    expected_n = {_norm_token(t) for t in NAMED_STATE_TERMS}
    got_h = set(hardening_to_named.keys())
    got_n = set(named_to_hardening.keys())

    missing_h = expected_h - got_h
    extra_h = got_h - expected_h
    missing_n = expected_n - got_n
    extra_n = got_n - expected_n

    problems: List[str] = []
    if missing_h:
        problems.append("missing hardening term(s): %s" % ", ".join(sorted(missing_h)))
    if extra_h:
        problems.append(
            "term(s) on neither/foreign hardening side: %s" % ", ".join(sorted(extra_h))
        )
    if missing_n:
        problems.append("missing NamedState term(s): %s" % ", ".join(sorted(missing_n)))
    if extra_n:
        problems.append(
            "term(s) on neither/foreign NamedState side: %s" % ", ".join(sorted(extra_n))
        )
    if problems:
        raise VocabularyMapError(
            "STATE-VOCABULARY-MAP bijection failure in %s — %s"
            % (path, "; ".join(problems))
        )

    return VocabularyMap(
        schema=schema,
        hardening_to_named={k: frozenset(v) for k, v in hardening_to_named.items()},
        named_to_hardening=dict(named_to_hardening),
        path=path,
    )


def load_vocabulary_map(root: Optional[Path] = None) -> VocabularyMap:
    """Load and validate ``artifacts/STATE-VOCABULARY-MAP.md``."""
    path = map_path(root)
    rel = MAP_RELPATH.replace("\\", "/")
    if not path.is_file():
        raise VocabularyMapError(
            "STATE-VOCABULARY-MAP not found at %s" % rel
        )
    text = path.read_text(encoding="utf-8")
    # Relative path string only — no absolute host paths in shipped messages.
    return parse_vocabulary_map_text(text, path=rel)


# --------------------------------------------------------------------------
# Table parsing helpers
# --------------------------------------------------------------------------


def _rows_from_table(table: Union[Sequence[Any], Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    if isinstance(table, Mapping):
        rows = table.get("rows", table.get("states", table.get("table")))
        if rows is None and any(k in table for k in _ROW_FIELDS):
            rows = [table]
        if rows is None:
            raise TableValidationError(
                "failure-state table has no rows — required rows missing: %s"
                % ", ".join(HARDENING_TERMS)
            )
    else:
        rows = table
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TableValidationError(
            "failure-state table rows must be a sequence of row objects"
        )
    out: List[Mapping[str, Any]] = []
    for idx, row in enumerate(rows):
        if isinstance(row, Mapping):
            out.append(row)
        else:
            out.append({"state": str(row), "user_visible": str(row), "trigger": ""})
    return out


def _row_term(row: Mapping[str, Any]) -> str:
    for key in _ROW_FIELDS:
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""


def _row_explicit_hardening(row: Mapping[str, Any]) -> Optional[str]:
    """Return an explicitly declared hardening term, if the row has one.

    Required-row completeness credits **only** explicit ``hardening`` /
    ``hardening_term`` / ``dependency`` / ``required_row`` fields — never a
    side-effect of naming a Mapped NamedState. A table is conformant only
    when complete (every hardening term answered by name), not when a
    NamedState token merely happens to map to one.
    """
    for key in ("hardening", "hardening_term", "dependency", "required_row"):
        if key in row and row[key] not in (None, ""):
            return _norm_hardening(row[key])
    return None


def _row_hardening(row: Mapping[str, Any], vmap: VocabularyMap) -> Optional[str]:
    """Resolve which hardening term a row answers (explicit, else inferred)."""
    explicit = _row_explicit_hardening(row)
    if explicit is not None:
        return explicit
    term = _row_term(row)
    if not term:
        return None
    # Direct hardening token as the state/name field?
    h = _norm_hardening(term)
    if h in vmap.hardening_to_named:
        return h
    # NamedState token → inferred hardening (used for reporting; not for
    # required-row completeness — see _row_explicit_hardening).
    n = _norm_token(term)
    return vmap.named_to_hardening.get(n)


def _row_user_visible(row: Mapping[str, Any]) -> str:
    """Return the row's user-visible string, or "" if omitted/blank.

    Does **not** fall back to the state token: every row must name its own
    user-visible string (empty ``user_visible`` is a table defect, not a
    cue to invent a label from ``state``).
    """
    for key in ("user_visible", "user_visible_string", "label", "visible", "text"):
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""



def _row_trigger(row: Mapping[str, Any]) -> str:
    for key in ("trigger", "when", "reason", "cause"):
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""


def _row_blob(row: Mapping[str, Any]) -> str:
    """Concatenate string fields for honesty-theater scanning."""
    parts = []
    for k, v in row.items():
        if v is None:
            continue
        parts.append(str(k))
        parts.append(str(v))
    return " ".join(parts).lower()


# --------------------------------------------------------------------------
# Validator
# --------------------------------------------------------------------------


def validate_failure_state_table(
    table: Union[Sequence[Any], Mapping[str, Any]],
    *,
    surface: str = "user",
    vocabulary_map: Optional[VocabularyMap] = None,
    root: Optional[Path] = None,
    require_all_hardening: bool = True,
) -> Dict[str, Any]:
    """Validate a surface failure-state table against the vocabulary map.

    Returns a small report dict on success. Raises
    :class:`TableValidationError` / :class:`HonestyTheaterError` on failure.

    GWT coverage:

    * missing ``backing-store-unreadable`` row → fails naming the missing row
    * Doctor tile in index/rebuild/reconcile language → honesty theater
    * term absent from the map → fails
    * unknown and empty must be separate rows (delegates to W6 merge rules)
    """
    vmap = vocabulary_map if vocabulary_map is not None else load_vocabulary_map(root)
    rows = _rows_from_table(table)

    # --- W6 merge / separate-row rules (unknown ≠ empty) -----------------
    try:
        _w6_validate_merges(table)
    except W6FailureStateTableError as exc:
        raise TableValidationError(str(exc)) from exc

    # --- Per-row: user_visible + trigger + mapped term -------------------
    # Completeness credits only *explicit* hardening keys so a bare
    # NamedState.unknown cannot silently satisfy backing-store-unreadable.
    covered_hardening: Set[str] = set()
    seen_named: Set[str] = set()
    unmapped: List[str] = []

    for idx, row in enumerate(rows):
        term = _row_term(row)
        explicit_h = _row_explicit_hardening(row)
        if not term and not explicit_h:
            raise TableValidationError(
                "failure-state table row %d has no state/hardening term" % idx
            )

        # Reject terms absent from both sides of the map.
        check_term = term or explicit_h or ""
        ntok = _norm_token(check_term)
        htok = _norm_hardening(check_term)
        if check_term and not vmap.is_known_term(check_term):
            # Explicit hardening key counts as known if it is a hardening term.
            if not (explicit_h and explicit_h in vmap.hardening_to_named):
                unmapped.append(check_term)

        if explicit_h and explicit_h not in vmap.hardening_to_named:
            unmapped.append(explicit_h)

        visible = _row_user_visible(row)
        if not visible:
            raise TableValidationError(
                "failure-state table row %r missing user-visible string"
                % (term or explicit_h or idx)
            )
        trigger = _row_trigger(row)
        if not trigger:
            raise TableValidationError(
                "failure-state table row %r missing trigger"
                % (term or explicit_h or idx)
            )

        if explicit_h:
            covered_hardening.add(explicit_h)
        if ntok in vmap.named_to_hardening:
            seen_named.add(ntok)

    if unmapped:
        raise TableValidationError(
            "failure-state table uses term(s) absent from STATE-VOCABULARY-MAP: %s"
            % ", ".join(unmapped)
        )

    # --- Required hardening rows (complete table, not merely present) ----
    if require_all_hardening:
        missing = [
            _norm_hardening(t)
            for t in HARDENING_TERMS
            if _norm_hardening(t) not in covered_hardening
        ]
        if missing:
            raise TableValidationError(
                "failure-state table missing required row(s): %s — a table is "
                "conformant only when complete, not when merely present"
                % ", ".join(missing)
            )

    # --- Honesty theater (surface-native enforcement) --------------------
    surface_key = (surface or "user").strip().lower().replace(" ", "-")
    if surface_key not in INDEX_BEARING_SURFACES:
        theater_hits: List[str] = []
        for idx, row in enumerate(rows):
            blob = _row_blob(row)
            # Word-boundary-ish scan for forbidden verbs.
            for verb in HONESTY_THEATER_VERBS:
                if re.search(r"\b%s\b" % re.escape(verb), blob):
                    theater_hits.append(
                        "row %d (%s) uses honesty-theater verb %r"
                        % (idx, _row_term(row), verb)
                    )
        if theater_hits:
            raise HonestyTheaterError(
                "honesty theater on surface %r — user-facing tables must use "
                "surface-native actions (open, run, attach, diagnose, preview, "
                "restart, tile render), not index/rebuild/reconcile. Offending: %s"
                % (surface, "; ".join(theater_hits))
            )

    return {
        "ok": True,
        "schema": vmap.schema,
        "surface": surface_key,
        "covered_hardening": sorted(covered_hardening),
        "row_count": len(rows),
        "map_path": vmap.path,
    }


def make_conformant_table(
    surface_action: str = "diagnose",
) -> List[Dict[str, str]]:
    """Build a minimal complete, surface-native failure-state table.

    Useful as a fixture for tests and as a template for surface waves.
    Every required hardening term is named explicitly; unknown and empty are
    SEPARATE rows; triggers use the surface's own action verb.
    """
    action = surface_action.strip().lower()
    if action in ("open",):
        cannot_state = "cannot_open"
    elif action in ("retry",):
        cannot_state = "cannot_retry"
    elif action in ("restart",):
        cannot_state = "cannot_restart"
    else:
        cannot_state = "cannot_run"
    return [
        {
            "hardening": "dependency-missing",
            "state": cannot_state,
            "user_visible": cannot_state,
            "trigger": "%s capability absent — cannot %s" % (action, action),
        },
        {
            "hardening": "dependency-slow-or-killed",
            "state": "timeout",
            "user_visible": "timeout",
            "trigger": "%s dependency slow or killed" % action,
        },
        {
            "hardening": "dependency-returns-garbage",
            "state": "measurement_failed",
            "user_visible": "measurement_failed",
            "trigger": "%s dependency returned garbage payload" % action,
        },
        {
            "hardening": "backing-store-unreadable",
            "state": "unknown",
            "user_visible": "unknown",
            "trigger": "%s backing store unreadable — did not successfully read" % action,
        },
        {
            "hardening": "empty-but-valid",
            "state": "empty",
            "user_visible": "empty",
            "trigger": "%s scope legitimately empty — nothing in scope" % action,
        },
        {
            "hardening": "empty-but-valid",
            "state": "zero_measured",
            "user_visible": "zero_measured",
            "trigger": "%s aggregation ran over existing scope; total is 0" % action,
        },
    ]


__all__ = [
    "HARDENING_TERMS",
    "HONESTY_THEATER_VERBS",
    "INDEX_BEARING_SURFACES",
    "MAP_RELPATH",
    "NAMED_STATE_TERMS",
    "SCHEMA",
    "SURFACE_NATIVE_ACTIONS",
    "HonestyTheaterError",
    "TableValidationError",
    "VocabularyMap",
    "VocabularyMapError",
    "load_vocabulary_map",
    "make_conformant_table",
    "map_path",
    "parse_vocabulary_map_text",
    "validate_failure_state_table",
]
