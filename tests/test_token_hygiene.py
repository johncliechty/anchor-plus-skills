import os
import json
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
import pytest
import shutil
import paths as _paths
import auth_session
import control_channel

#: A distinctive shared secret the hygiene scan hunts for in logs/journal.
MASTER_TOKEN = "tok-hygiene-DO-NOT-LEAK-9f3a"

def test_token_hygiene_lifecycle(tmp_path, monkeypatch):
    """
    Wave 8 Token-hygiene CI test.
    Scripts the onboard/claim/agent-spawn/CLI-invocation/restart sequence
    and asserts secret absence in logs/journal/temp.
    """
    # Setup hermetic environment. A DISTINCTIVE master token so the
    # secret-absence scan below is hunting for something real.
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_PORT", "8799")
    monkeypatch.setenv("ANCHOR_TOKEN", MASTER_TOKEN)
    _paths.ensure_data_dirs()
    
    # We will just simulate the actions using the Python APIs to avoid starting the server
    # since we just need to assert secret absence in files.
    
    # 1. Onboard / Claim
    nonce = auth_session.arm_claim()
    session_id = auth_session.mint_session("bootstrap")
    assert session_id is not None
    
    # 2. Agent spawn
    # Generate some logs and journal entries
    # RELOAD under the tmp env before touching anchor_gui: LOGS_DIR is bound at
    # import time, and this module's own imports (auth_session/control_channel)
    # can pull anchor_gui in during collection — i.e. before monkeypatch. Without
    # the reload the run writes into the REAL data dir and the tmp scan below
    # finds nothing to check.
    import importlib
    importlib.reload(_paths)
    import anchor_gui
    log_change = importlib.reload(anchor_gui).log_change
    # log_change takes ONE argument — the message line it appends to today's
    # log. (This call used to pass (path, action, detail), a signature the
    # product has never had, so the whole hygiene test died on a TypeError
    # before reaching a single secret-absence assertion.)
    log_change("add_task: Test task")
    
    # The single append path is journal.emit (the enforced choke point). This
    # used to call a `journal.Journal(...).record(...)` class the module has
    # never exported, so the test died here and NONE of the secret-absence
    # assertions below ever ran.
    import journal
    journal.emit("token-hygiene", "session.started",
                 correlation_id="token-hygiene-ci",
                 folder_path=str(tmp_path),
                 payload={"session": session_id, "action": "test"})
    
    # 3. CLI invocation
    # anchor pair
    code = control_channel.generate_pairing_code()
    assert len(code) == 11
    assert "-" in code
    
    # 4. Assert absence of secrets.
    # The master token lives in the ANCHOR_TOKEN ENV (paths.expected_token) —
    # NOT in a `<data>/token` file. This block used to be guarded by
    # `if (tmp_path / "token").exists()`, which is never true, so every
    # assertion below was skipped and the test passed while checking nothing.
    secret = _paths.expected_token()
    assert secret == MASTER_TOKEN, "the hygiene run must have a real secret to hunt for"

    scanned = 0
    for log_file in (tmp_path / "logs").glob("*.md"):
        content = log_file.read_text(encoding="utf-8")
        scanned += 1
        assert secret not in content, f"Master token leaked in {log_file.name}"
        assert session_id not in content, f"Session ID leaked in {log_file.name}"
    assert scanned, "no log file was produced — the scan proved nothing"

    # A project journal lives at <folder>/.anchor/projects/<id>/journal.jsonl
    # (journal.journal_path_for) — NOT under a <data>/journal/ directory.
    scanned = 0
    for j_file in tmp_path.rglob("*.jsonl"):
        content = j_file.read_text(encoding="utf-8")
        scanned += 1
        assert secret not in content, f"Master token leaked in {j_file.name}"
        # session_id IS allowed in the journal (it identifies the session);
        # the shared secret never is.
    assert scanned, "no journal file was produced — the scan proved nothing"
