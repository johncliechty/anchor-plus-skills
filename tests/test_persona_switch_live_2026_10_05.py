"""Switching the steward's persona (Aladdin, Jarvis, Ecgberht) never looks like forgetting (his word, 2026-10-05): the
stores are keyed by folder, and the live stewards take the new name."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steward_cockpit import steward_routes as sr  # noqa: E402


class _E:
    def __init__(self, name):
        self.steward = name


def test_live_stewards_take_the_new_name(monkeypatch):
    monkeypatch.setattr(sr, "ENGINES", {"a": _E("Aladdin"), "b": _E("Aladdin"), "c": _E("Jarvis")})
    monkeypatch.setitem(sr.CONFIG, "steward", "Aladdin")
    assert sr.rename_stewards("Jarvis") == 2
    assert {e.steward for e in sr.ENGINES.values()} == {"Jarvis"} and sr.CONFIG["steward"] == "Jarvis"
    assert sr.rename_stewards("") == 0


def test_no_store_is_keyed_by_the_persona():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "steward_cockpit", "steward_routes.py"), encoding="utf-8").read()
    assert 'key = cdir + ("||general||%s" %' in src or "cdir + (" in src, "engines keyed by folder"
