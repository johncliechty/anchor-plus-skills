"""Shared conformance assertion engine for surface waves (W8).

Importable by every surface wave under the scoped gate:

* :mod:`tests.conformance.tri_state` — unknown ≠ empty ≠ zero harness
* :mod:`tests.conformance.table_validator` — failure-state table + vocabulary map
* :mod:`tests.conformance.html_assert` — visible text nodes + node --check
"""
from __future__ import annotations

from tests.conformance.html_assert import (
    assert_visible_text_contains,
    extract_script_blocks,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import (
    HonestyTheaterError,
    TableValidationError,
    VocabularyMapError,
    load_vocabulary_map,
    validate_failure_state_table,
)
from tests.conformance.tri_state import (
    TriStateCollapseError,
    TriStateHarness,
    assert_tri_state,
    run_tri_state,
)

__all__ = [
    "HonestyTheaterError",
    "TableValidationError",
    "TriStateCollapseError",
    "TriStateHarness",
    "VocabularyMapError",
    "assert_tri_state",
    "assert_visible_text_contains",
    "extract_script_blocks",
    "load_vocabulary_map",
    "node_check_scripts",
    "run_tri_state",
    "validate_failure_state_table",
    "visible_text_nodes",
]
