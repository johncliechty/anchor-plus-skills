"""Effort refs encode folder names without changing the target or containment."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from steward_cockpit.campaign_parts import resolve_ref


@pytest.mark.parametrize("heading,title", [
    ("3D imaging", "3D imaging"),
    ("Ecgberht - Face", "3D Parametric Representation"),
])
def test_encoded_effort_opens_exact_directory(tmp_path, heading, title):
    effort = tmp_path / "3D Parametric Representation"
    effort.mkdir()
    (effort / "ECGBERHT.md").write_text("# " + heading + "\n", encoding="utf-8")
    entry = {"id": "p", "name": "Data Compression", "folder_path": str(tmp_path)}
    result = resolve_ref("effort:p/3D%20Parametric%20Representation", lookup=lambda _: entry)
    assert result["broken"] is False
    assert result["dir"] == "3D Parametric Representation"
    assert result["href"] == "/project/p?dir=3D%20Parametric%20Representation"
    assert result["what"] == title


@pytest.mark.parametrize("sub", ["%2e%2e", "outside%2fchild", "outside%5cchild"])
def test_decoding_cannot_escape_effort_boundary(tmp_path, sub):
    entry = {"id": "p", "name": "Project", "folder_path": str(tmp_path)}
    result = resolve_ref("effort:p/" + sub, lookup=lambda _: entry)
    assert result["broken"] is True
    assert "one directory" in result["gap"]
