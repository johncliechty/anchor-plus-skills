"""Code opens where it runs (John, 2026-09-07): notebooks in the project's own JupyterLab, short code as
a notebook, long code in the editor, live links from the register. The gate file for
planning/code-windows-2026-09-07; wave 1 extends it. This seed pins today's truth: the preview port
guard never yields 8777 and the register still treats an external URL as text."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preview_server  # noqa: E402
from steward_cockpit import steward_campaign as campaign  # noqa: E402


def test_free_port_is_never_the_live_port():
    for _ in range(5):
        assert preview_server.pick_free_port() != 8777


def test_external_url_where_cell_is_text_today():
    td = tempfile.mkdtemp(prefix="code-windows-seed-")
    Path(td, "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n"
        "| lab | http://evil.example/lab | 2026-09-07 | 1 |\n", encoding="utf-8")
    it = campaign.read_deliverables(td)["items"][0]
    assert it["openable"] is False and it.get("route") is None
