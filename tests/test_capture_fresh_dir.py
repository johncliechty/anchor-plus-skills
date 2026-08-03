"""Wave 2 FIX W2-m3: capture must not lose ideas on a fresh data dir.

Previously both `anchor.capture_inbox` and `anchor_gui.capture_inbox` guarded
the inbox append with `if INBOX_MD.exists():`, so against a fresh/empty
ANCHOR_DATA_DIR the capture was silently dropped. Now INBOX.md is created
first, so the captured line is always present (zero loss).
"""
import importlib

import paths


def test_cli_capture_creates_inbox_on_fresh_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)

    import anchor
    cli = importlib.reload(anchor)

    # Fresh dir: INBOX.md must NOT exist yet.
    assert not cli.INBOX_MD.exists()

    cli.capture_inbox("Look into MIT fellowship", domain="academic")

    assert cli.INBOX_MD.exists(), "capture must create INBOX.md on a fresh dir"
    content = cli.INBOX_MD.read_text(encoding="utf-8")
    assert "Look into MIT fellowship" in content
    assert "[academic]" in content


def test_gui_capture_creates_inbox_on_fresh_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)

    import anchor_gui
    gui = importlib.reload(anchor_gui)

    assert not gui.INBOX_MD.exists()

    gui.capture_inbox("Capture via GUI path", domain="writing")

    assert gui.INBOX_MD.exists(), "capture_inbox must create INBOX.md on a fresh dir"
    content = gui.INBOX_MD.read_text(encoding="utf-8")
    assert "Capture via GUI path" in content
    assert "[writing]" in content


def test_capture_preserves_existing_inbox(monkeypatch, tmp_path):
    """When INBOX.md already exists, behavior is unchanged (append, no clobber)."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)

    import anchor_gui
    gui = importlib.reload(anchor_gui)

    gui.INBOX_MD.write_text("# Inbox\n\n- existing item\n", encoding="utf-8")
    gui.capture_inbox("New idea", domain="family")

    content = gui.INBOX_MD.read_text(encoding="utf-8")
    assert "existing item" in content  # not clobbered
    assert "New idea" in content
