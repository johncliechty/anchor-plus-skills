"""Folder move (John, 2026-09-05: "when I try and move the project tile from the Ungrouped folder to the
teaching folder nothing happens"). Source-level gate: the drop → regroup → reload path remembers the
destination folder OPEN, so the moved row is visible after the reload (folders close by default)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SRC = (Path(__file__).resolve().parent.parent / "anchor_gui.py").read_text(encoding="utf-8")


def test_destination_folder_is_remembered_open_before_the_regroup_reload():
    assert "function _rndOpenFolderNext(group)" in SRC
    # the helper writes the same OPEN set the folder init restores from
    helper = SRC[SRC.index("function _rndOpenFolderNext(group)"):SRC.index("function rndToggleFolder(headEl)")]
    assert "_rndCollapsedSet()" in helper and "_rndSaveCollapsed(set)" in helper
    # "Just group" and the refused-disk-move fallback both pass through rndMoveConfirm, which opens the
    # destination first; the no-dialog fallback does too
    confirm = SRC[SRC.index("function rndMoveConfirm(pid, group, onDisk)"):SRC.index("// Make project rows draggable")]
    assert confirm.index("_rndOpenFolderNext(group);") < confirm.index("apiCall('/api/rnd/set_group'")
    dialog = SRC[SRC.index("function rndMoveDialog(pid, group, folder)"):SRC.index("function rndMoveCancel()")]
    assert "_rndOpenFolderNext(group);" in dialog


def test_the_drop_target_is_the_folder_header_and_rows_are_draggable():
    assert "head.addEventListener('drop'" in SRC
    assert re.search(r"row\.addEventListener\('dragstart'", SRC)
