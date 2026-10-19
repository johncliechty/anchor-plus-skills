"""W0 of the steward revision (2026-09-28): the speaking boundaries — Anchor's mirror equals the engine's list.

The engine's list lives in Ecgberht ``engine/boundaries.mjs``; this test parses it when the engine is on this host
(``ANCHOR_ECGBERHT_DIR`` or ``C:\\dev\\Ecgberht``) and skips honestly when it is not. The mirror's own shape is
tested unconditionally."""
import os
import re
from pathlib import Path

import pytest

from steward_cockpit import boundaries


def test_mirror_shape():
    assert boundaries.SPEAKING_BOUNDARIES == (
        "page_open", "card_open", "turn_submitted", "step_closed", "run_finished")
    assert boundaries.SPEAKING_BOUNDARIES_VERSION == 1
    assert boundaries.is_speaking_boundary("card_open") is True
    assert boundaries.is_speaking_boundary("another boundary") is False
    assert boundaries.is_speaking_boundary("Card_Open") is False
    assert boundaries.is_speaking_boundary(None) is False


def _engine_file():
    for base in (os.environ.get("ANCHOR_ECGBERHT_DIR"), r"C:\dev\Ecgberht"):
        if base and (Path(base) / "engine" / "boundaries.mjs").is_file():
            return Path(base) / "engine" / "boundaries.mjs"
    return None


def test_mirror_equals_engine_list():
    f = _engine_file()
    if f is None:
        pytest.skip("the engine is not on this host")
    text = f.read_text(encoding="utf-8")
    block = re.search(r"SPEAKING_BOUNDARIES = Object\.freeze\(\[(.*?)\]\)", text, re.S)
    assert block, "the engine's list was not found"
    names = re.findall(r"'([a-z_]+)'", block.group(1))
    assert tuple(names) == boundaries.SPEAKING_BOUNDARIES
    ver = re.search(r"SPEAKING_BOUNDARIES_VERSION = (\d+)", text)
    assert ver and int(ver.group(1)) == boundaries.SPEAKING_BOUNDARIES_VERSION
