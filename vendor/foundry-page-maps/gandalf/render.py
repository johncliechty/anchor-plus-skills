"""Render the catalog through the shared Foundry display builder."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))
from render_display import render

if __name__ == "__main__":
    render(HERE, json.loads((HERE / "maps.json").read_text(encoding="utf-8")))
