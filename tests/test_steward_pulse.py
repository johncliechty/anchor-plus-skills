"""Run-pulse helpers (2026-08-07, John's inspect-naturally ask).

The pulse tile shows a live run's cleaned output + the campaign North star.
These pin the two pure helpers; the endpoint itself is a thin read composed
of load_run_record + read_since, both covered elsewhere.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anchor_gui as ag


def test_strip_terminal_noise_removes_ansi_and_controls():
    raw = "\x1b[32m⏱ wave 3/7\x1b[0m\r\n\x1b]0;title\x07next line\x1b[2K"
    out = ag._strip_terminal_noise(raw)
    assert "⏱ wave 3/7" in out
    assert "next line" in out
    assert "\x1b" not in out
    assert "\r" not in out


def test_strip_terminal_noise_never_raises():
    assert ag._strip_terminal_noise(None) is not None
    assert ag._strip_terminal_noise(12345) == "12345"


def test_read_face_north_star_parses_the_blockquote(tmp_path):
    (tmp_path / "ECGBERHT.md").write_text(
        "# Ecgberht — Face\n\nintro\n\n## North star\n\n"
        "> Revise **BA 815** for 2026: keep the backbone,\n"
        "> integrate AI throughout.\n\n---\n\n## Active effort\n",
        encoding="utf-8")
    star = ag._read_face_north_star(str(tmp_path))
    assert star == "Revise BA 815 for 2026: keep the backbone, integrate AI throughout."


def test_read_face_north_star_honest_absent(tmp_path):
    assert ag._read_face_north_star(str(tmp_path)) is None
    (tmp_path / "ECGBERHT.md").write_text("# Face\nno star section\n",
                                          encoding="utf-8")
    assert ag._read_face_north_star(str(tmp_path)) is None
