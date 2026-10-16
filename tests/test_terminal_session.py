"""Wave 3 — ConPTY terminal session service + transport + auth (hermetic).

Locks the v3 live terminal session service (MASTER-PLAN §D, Implementation-Plan
Wave 3): ``terminal_session.start_session`` ties Wave-1 ``pty_manager`` (stub
backend) + Wave-2 ``session_registry``/``worktrees`` into one worktree-isolated,
registered, RUNNING session; ``attach`` replays the live screen buffer
(reattach); ``input``/``read_since``/``resize``/``kill`` drive it; detach is
implicit (NOTHING is killed on detach). The browser transport is a hand-rolled
stdlib WebSocket (``/api/rnd/term_ws``) + an SSE-out/POST-in fallback
(``/api/rnd/term_stream2`` + ``/api/rnd/term_input2``), all token-authed.

Hermetic: NO real claude/gemini and NO real PTY — ``ANCHOR_PTY_BACKEND=stub``
everywhere, a TEMP git repo per test for the worktree, a tmp data dir + tmp
worktree base. NO worktree is ever created off the real ``C:\\dev\\Anchor`` repo.
The WS/SSE integration tests are bounded so they never hang.
"""
import importlib
import json
import socket
import subprocess
import threading
import urllib.error
import urllib.request

import pytest


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY backend + a temp git repo.

    Mirrors the test_worktrees / test_terminal_repl fixture pattern: set the
    env, reload the stack in dependency order, build a hermetic temp git repo,
    register a project rooted at it. Auth is OFF by default (ANCHOR_TOKEN
    deleted); auth tests set it explicitly and reload.
    """
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    import paths
    importlib.reload(paths)
    import pty_manager
    importlib.reload(pty_manager)
    import rnd_registry
    importlib.reload(rnd_registry)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    yield {
        "ts": terminal_session, "pty": pty_manager, "reg": session_registry,
        "wt": worktrees, "rnd": rnd_registry, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data, "monkeypatch": monkeypatch,
    }
    # Reap any live stub PTYs so nothing leaks across tests.
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ── Lifecycle over the service ───────────────────────────────────────────────

def test_start_creates_worktree_and_registers_running(env):
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    from pathlib import Path
    rec = ts.start_session(pid, "plan", backend="claude")
    sid = rec["session_id"]
    assert rec["status"] == reg.STATUS_RUNNING
    assert rec["project_id"] == pid
    assert rec["lane"] == "plan"
    assert rec["backend"] == "claude"
    # The worktree exists under the managed base, OUTSIDE the real repo.
    assert Path(rec["worktree_path"]).exists()
    assert str(env["wbase"]) in rec["worktree_path"]
    assert str(env["repo"]) not in rec["worktree_path"]
    # The registry persisted it and the PTY is live under the SAME id.
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING
    assert sid in env["pty"].live_sessions()


def test_input_then_read_and_attach_show_echo(env):
    ts = env["ts"]
    rec = ts.start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]
    # The stub child echoes written input into its output buffer.
    assert ts.input(sid, "hello-pty")["ok"] is True
    out = ts.read_since(sid, 0)
    assert "hello-pty" in out["text"]
    assert out["status"] == "running"
    # attach replays the FULL live buffer (reattach contract).
    att = ts.attach(sid)
    assert att["ok"] is True
    assert "hello-pty" in att["buffer"]
    assert att["status"] == "running"


def test_detach_keeps_running_then_reattach_replays(env):
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    ts.input(sid, "line-one\n")
    # "Detach" = simply stop reading. NOTHING is killed: the process is alive and
    # the session is still RUNNING in the registry.
    assert sid in env["pty"].live_sessions()
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING
    ts.input(sid, "line-two\n")
    # Reattach: the full buffer replays (both lines, from cursor 0).
    att = ts.attach(sid)
    assert "line-one" in att["buffer"]
    assert "line-two" in att["buffer"]
    assert att["status"] == "running"


def test_kill_marks_terminal_removes_worktree_leaves_others(env):
    ts, reg = env["ts"], env["reg"]
    from pathlib import Path
    a = ts.start_session(env["pid"], "plan", backend="claude")
    b = ts.start_session(env["pid"], "research", backend="claude")
    a_path = Path(a["worktree_path"])
    b_path = Path(b["worktree_path"])
    assert a_path.exists() and b_path.exists()

    out = ts.kill(a["session_id"])
    assert out["ok"] is True
    # A's registry record is terminal; its worktree is gone; PTY reaped.
    assert reg.get_session(a["session_id"])["status"] in reg.TERMINAL_STATUSES
    assert not a_path.exists()
    assert a["session_id"] not in env["pty"].live_sessions()
    # B is untouched: still running, worktree intact, PTY live.
    assert reg.get_session(b["session_id"])["status"] == reg.STATUS_RUNNING
    assert b_path.exists()
    assert b["session_id"] in env["pty"].live_sessions()
    # The real build repo was never touched.
    assert str(env["repo"]) not in str(a_path)


def test_unknown_session_calls_are_clean(env):
    ts = env["ts"]
    assert ts.input("nope", "x") == {"ok": False, "reason": "unknown-session"}
    assert ts.read_since("nope", 0) == {"ok": False, "reason": "unknown-session"}
    assert ts.resize("nope", 80, 24) == {"ok": False, "reason": "unknown-session"}
    att = ts.attach("nope")
    assert att["ok"] is True and att["status"] == "dead" and att["buffer"] == ""
    # kill of an unknown session is tolerated (no crash).
    out = ts.kill("nope")
    assert out["ok"] is True and out["pty_killed"] is False


def test_unknown_project_and_engine_policy(env):
    ts = env["ts"]
    with pytest.raises(ts.TerminalSessionError):
        ts.start_session("no-such-pid", "plan", backend="claude")
    # Gemini is now allowed on plan/build.
    rec_plan = ts.start_session(env["pid"], "plan", backend="gemini")
    assert rec_plan["backend"] == "gemini"
    with pytest.raises(ts.TerminalSessionError):
        ts.start_session(env["pid"], "plan", backend="bogus")
    # Gemini on research is allowed.
    rec = ts.start_session(env["pid"], "research", backend="gemini")
    assert rec["backend"] == "gemini"


def test_list_sessions_passthrough(env):
    ts = env["ts"]
    a = ts.start_session(env["pid"], "plan", backend="claude")
    b = ts.start_session(env["pid"], "research", backend="claude")
    ids = {r["session_id"] for r in ts.list_sessions(project_id=env["pid"])}
    assert {a["session_id"], b["session_id"]} <= ids


# ── FIX 5: unknown lane is rejected BEFORE any worktree/PTY/session ──────────

def test_unknown_lane_creates_no_worktree_pty_or_session(env):
    """A lane typo must raise BEFORE minting a worktree, PTY, or registry row."""
    ts, reg = env["ts"], env["reg"]
    before_live = set(env["pty"].live_sessions())
    before_sessions = {r["session_id"] for r in reg.list_sessions()}
    with pytest.raises(ts.TerminalSessionError):
        ts.start_session(env["pid"], "planx", backend="claude")
    # No new PTY, no new registry session.
    assert set(env["pty"].live_sessions()) == before_live
    assert {r["session_id"] for r in reg.list_sessions()} == before_sessions
    # And no worktree branch was left behind.
    out = _git(env["repo"], "worktree", "list", "--porcelain")
    assert "anchor/session/" not in out.stdout
    # The grass lane IS valid (a 5th lane for future ideas).
    rec = ts.start_session(env["pid"], "grass", backend="claude")
    assert rec["lane"] == "grass"


# ── v13 Wave 1 (#12b): dashboard-scoped zombie terminal returns a record ─────

def test_zombie_lane_dashboard_scope_starts_session(env):
    """``/api/rnd/zombie_terminal_start`` launches a ``zombie`` lane session on
    the special ``__dashboard__`` project. Before #12b the ``zombie`` lane was
    an unknown lane → ``TerminalSessionError`` → the endpoint returned 400. Now
    it must start cleanly and return a registered RUNNING session record (the
    bare-shell briefing is folded in via ``seed_context``)."""
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(
        "__dashboard__", "zombie", backend="claude",
        label="zombie-hunter", seed_context="## Zombie sweep briefing\n")
    assert rec is not None
    assert rec.get("session_id")
    assert rec["lane"] == "zombie"
    assert rec["status"] == reg.STATUS_RUNNING
    # The session is registered + live (so the endpoint hands back a real id).
    assert reg.get_session(rec["session_id"]) is not None
    assert rec["session_id"] in set(env["pty"].live_sessions())


# ── FIX 1: register_session failure rolls back BOTH PTY and worktree ─────────

def test_register_failure_rolls_back_pty_and_worktree(env, monkeypatch):
    """If register_session raises AFTER the PTY is started, neither the PTY nor
    the worktree may leak as an orphan invisible to reconcile."""
    ts, reg = env["ts"], env["reg"]
    before_live = set(env["pty"].live_sessions())

    def _boom(*a, **k):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(reg, "register_session", _boom)
    with pytest.raises(ts.TerminalSessionError):
        ts.start_session(env["pid"], "plan", backend="claude")
    # No PTY leaked.
    assert set(env["pty"].live_sessions()) == before_live
    # The worktree is gone — git worktree list is clean of session worktrees.
    out = _git(env["repo"], "worktree", "list", "--porcelain")
    assert "anchor/session/" not in out.stdout
    # No stray session branch.
    br = _git(env["repo"], "branch", "--list", "anchor/session/*")
    assert br.stdout.strip() == ""


# ── FIX 4: attach surfaces dropped scrollback honestly ──────────────────────

def test_attach_reports_dropped_and_truncated(env, monkeypatch):
    """When the bounded buffer drops older scrollback, attach reports it."""
    ts = env["ts"]
    # This test reasons about the bounded buffer's drop/truncate accounting from
    # USER writes alone, so disable the v4 lane skill-seed (empty override = bare
    # shell) to keep the start buffer empty.
    monkeypatch.setenv("ANCHOR_TERMINAL_SEED", "")
    # Shrink the buffer so a modest write overflows it.
    monkeypatch.setattr(env["pty"], "MAX_BUFFER_CHARS", 16)
    rec = ts.start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    ts.input(sid, "X" * 100)  # far exceeds the 16-char window
    att = ts.attach(sid)
    assert att["ok"] is True
    assert att["dropped"] > 0
    assert att["truncated"] is True
    # A fresh session with no overflow reports no truncation.
    rec2 = ts.start_session(env["pid"], "research", backend="claude")
    ts.input(rec2["session_id"], "tiny")
    att2 = ts.attach(rec2["session_id"])
    assert att2["dropped"] == 0
    assert att2["truncated"] is False


# ── WebSocket frame codec — PURE unit tests (no socket) ─────────────────────

def test_ws_accept_key_rfc_example():
    import anchor_gui
    assert anchor_gui.ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") \
        == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def _mask_client_frame(opcode, payload):
    """Build a MASKED client->server frame (clients ALWAYS mask)."""
    import os
    import struct
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    b0 = 0x80 | (opcode & 0x0F)
    n = len(payload)
    mask = os.urandom(4)
    if n < 126:
        header = struct.pack(">BB", b0, 0x80 | n)
    elif n < (1 << 16):
        header = struct.pack(">BBH", b0, 0x80 | 126, n)
    else:
        header = struct.pack(">BBQ", b0, 0x80 | 127, n)
    masked = bytes(payload[i] ^ mask[i & 3] for i in range(n))
    return header + mask + masked


def test_ws_codec_roundtrip_masked_client_frame():
    import anchor_gui
    # Encode a server text frame and decode it back (round-trip, unmasked).
    frame = anchor_gui.encode_text_frame("héllo")
    msgs, rest = anchor_gui.decode_frames(frame)
    assert rest == b""
    assert len(msgs) == 1
    op, payload = msgs[0]
    assert op == anchor_gui.WS_OP_TEXT
    assert payload.decode("utf-8") == "héllo"

    # Decode a MASKED client frame (the real direction the server must unmask).
    cframe = _mask_client_frame(anchor_gui.WS_OP_TEXT, "type this")
    msgs2, rest2 = anchor_gui.decode_frames(cframe)
    assert rest2 == b""
    assert msgs2[0][1].decode("utf-8") == "type this"

    # A partial buffer returns no messages + carries the bytes forward.
    msgs3, rest3 = anchor_gui.decode_frames(cframe[:3])
    assert msgs3 == []
    assert rest3 == cframe[:3]
    # Concatenated frames decode as two messages.
    two = _mask_client_frame(anchor_gui.WS_OP_TEXT, "aaa") \
        + _mask_client_frame(anchor_gui.WS_OP_TEXT, "bbb")
    msgs4, _ = anchor_gui.decode_frames(two)
    assert [m[1].decode() for m in msgs4] == ["aaa", "bbb"]


def _client_frame(opcode, payload, fin=True, masked=True):
    """Build a client->server frame with explicit FIN/MASK control (for codec
    unit tests of fragmentation + the unmasked-frame protocol error)."""
    import os
    import struct
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    b0 = (0x80 if fin else 0x00) | (opcode & 0x0F)
    n = len(payload)
    mask_bit = 0x80 if masked else 0x00
    if n < 126:
        header = struct.pack(">BB", b0, mask_bit | n)
    elif n < (1 << 16):
        header = struct.pack(">BBH", b0, mask_bit | 126, n)
    else:
        header = struct.pack(">BBQ", b0, mask_bit | 127, n)
    if not masked:
        return header + bytes(payload)
    mask = os.urandom(4)
    masked_payload = bytes(payload[i] ^ mask[i & 3] for i in range(n))
    return header + mask + masked_payload


# ── FIX 3: a frame declaring a length > MAX_WS_FRAME signals close ───────────

def test_ws_codec_oversized_frame_signals_close():
    import anchor_gui
    import struct
    # Header ALONE declares a payload bigger than MAX_WS_FRAME (no payload bytes
    # supplied) — the codec must NOT wait/allocate; it signals a close.
    huge = anchor_gui.MAX_WS_FRAME + 1
    b0 = 0x80 | anchor_gui.WS_OP_TEXT
    header = struct.pack(">BBQ", b0, 0x80 | 127, huge) + b"\x00\x00\x00\x00"
    msgs, rest = anchor_gui.decode_frames(header)
    assert msgs and msgs[0][0] == anchor_gui.WS_SIGNAL_CLOSE
    # No partial buffering toward the huge allocation.
    assert rest == b""


# ── FIX 6: fragmentation reassembly + reject unmasked client data frame ──────

def test_ws_codec_reassembles_fragmented_message():
    import anchor_gui
    # FIN=0 TEXT "abc" then FIN=1 CONTINUATION "def" -> ONE message "abcdef".
    part1 = _client_frame(anchor_gui.WS_OP_TEXT, "abc", fin=False)
    part2 = _client_frame(anchor_gui.WS_OP_CONT, "def", fin=True)
    state = {}
    msgs1, rest1 = anchor_gui.decode_frames(part1, state)
    # No complete message yet — the lone fragment is NOT delivered.
    assert msgs1 == []
    msgs2, rest2 = anchor_gui.decode_frames(rest1 + part2, state)
    assert len(msgs2) == 1
    op, payload = msgs2[0]
    assert op == anchor_gui.WS_OP_TEXT
    assert payload.decode("utf-8") == "abcdef"


def test_ws_codec_unmasked_client_frame_is_protocol_error():
    import anchor_gui
    frame = _client_frame(anchor_gui.WS_OP_TEXT, "nope", masked=False)
    # The pump decodes client frames with require_mask=True (RFC 6455 §5.1).
    msgs, rest = anchor_gui.decode_frames(frame, require_mask=True)
    # The unmasked client data frame is NOT parsed as valid input; it signals a
    # protocol-error close.
    assert msgs and msgs[0][0] == anchor_gui.WS_SIGNAL_CLOSE


# ── Auth: terminal endpoints are 401 without a token when ANCHOR_TOKEN set ──

def _reload_gui_with_token(monkeypatch, token):
    """Reload paths + anchor_gui with ANCHOR_TOKEN set so auth is ON."""
    monkeypatch.setenv("ANCHOR_TOKEN", token)
    import paths
    importlib.reload(paths)
    import anchor_gui
    return importlib.reload(anchor_gui)


def _serve(gui):
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port, t


# Placeholder token values (on the distro-scan allowlist so the no-secrets scan
# never flags this test file). They still exercise the real auth path.
_TOK = "tok-123"
_HDR = "X-Anchor-Token"


def test_get_terminal_endpoint_401_without_token(env):
    """A GET terminal endpoint (term_stream2) is 401 when a token is configured
    and the ?token= is missing/wrong; correct token is allowed."""
    gui = _reload_gui_with_token(env["monkeypatch"], _TOK)
    rec = env["ts"].start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    server, port, t = _serve(gui)
    try:
        # No token -> 401.
        url = f"http://127.0.0.1:{port}/api/rnd/term_stream2?session={sid}"
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(url, timeout=10)
        assert ei.value.code == 401
        # Wrong token -> 401.
        url_bad = url + "&token=nope"
        with pytest.raises(urllib.error.HTTPError) as ei2:
            urllib.request.urlopen(url_bad, timeout=10)
        assert ei2.value.code == 401
        # Correct token -> the SSE stream opens (200) and terminates.
        url_ok = (url + "&token=" + _TOK + "&poll=0.02&max_ticks=10&hb=2")
        with urllib.request.urlopen(url_ok, timeout=10) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "event:" in body  # well-formed SSE, no hang
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


def test_post_terminal_endpoint_401_without_token(env):
    """A POST terminal endpoint (term_input2) is 401 without the token, allowed
    with it (the standard POST middleware enforces this)."""
    gui = _reload_gui_with_token(env["monkeypatch"], _TOK)
    rec = env["ts"].start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    server, port, t = _serve(gui)
    try:
        # No token -> 401.
        body = json.dumps({"session": sid, "data": "x"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/term_input2", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=10)
        assert ei.value.code == 401
        # With the token in the X-Anchor-Token header -> allowed (the standard
        # POST middleware path; header is preferred over the body field).
        body_ok = json.dumps({"session": sid, "data": "typed\n"}).encode("utf-8")
        req_ok = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/term_input2", data=body_ok,
            headers={"Content-Type": "application/json", _HDR: _TOK},
            method="POST")
        with urllib.request.urlopen(req_ok, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        # The byte reached the PTY (echoed into the stub buffer).
        assert "typed" in env["ts"].read_since(sid, 0)["text"]
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


def test_ws_handshake_401_without_token(env):
    """A WS handshake to term_ws is rejected (no 101) without the token."""
    gui = _reload_gui_with_token(env["monkeypatch"], _TOK)
    rec = env["ts"].start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    server, port, t = _serve(gui)
    try:
        resp_line = _ws_handshake_raw(port, f"/api/rnd/term_ws?session={sid}",
                                      key="dGhlIHNhbXBsZSBub25jZQ==")
        # Unauthorized: NOT a 101 upgrade.
        assert "101" not in resp_line
        assert "401" in resp_line
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


# ── WS integration: real hand-rolled handshake + echo round-trip ────────────

def _ws_handshake_raw(port, path, key, token=None, timeout=8):
    """Open a raw socket, send a WS handshake, return the status line text.

    Returns the first response line (and leaves the socket closed). Used by the
    401 negative test. The positive round-trip test uses _ws_roundtrip below.
    """
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        s.sendall(req.encode("ascii"))
        s.settimeout(timeout)
        data = s.recv(4096).decode("latin-1", "replace")
        return data.split("\r\n", 1)[0]
    finally:
        s.close()


def test_ws_full_roundtrip_echo(env):
    """Full WS path: 101 handshake over a stdlib socket, send a MASKED text
    frame, read back the echoed server frame from the stub session. Bounded so
    it never hangs."""
    import anchor_gui
    import paths
    env["monkeypatch"].delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)
    gui = importlib.reload(anchor_gui)
    rec = env["ts"].start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    server, port, t = _serve(gui)
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=8)
        s.settimeout(8)
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        path = f"/api/rnd/term_ws?session={sid}&poll=0.02&max_ticks=200"
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        s.sendall(req.encode("ascii"))
        # Read the handshake response (up to the blank line).
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(1024)
            if not chunk:
                break
            buf += chunk
        head = buf.decode("latin-1", "replace")
        assert "101" in head.split("\r\n", 1)[0]
        assert gui.ws_accept_key(key).lower() in head.lower()

        # Send a MASKED client text frame -> the stub echoes it back to us.
        s.sendall(_mask_client_frame(gui.WS_OP_TEXT, "PING-OVER-WS"))

        # Read frames back until we see our echoed bytes (bounded by timeout).
        seen = b""
        deadline_iters = 50
        leftover = buf.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in buf else b""
        acc = leftover
        for _ in range(deadline_iters):
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            acc += chunk
            msgs, acc = gui.decode_frames(acc)
            for op, payload in msgs:
                if op in (gui.WS_OP_TEXT, gui.WS_OP_BINARY):
                    seen += payload
            if b"PING-OVER-WS" in seen:
                break
        s.close()
        assert b"PING-OVER-WS" in seen
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


# ── SSE fallback integration: term_stream2 carries echoed bytes + ends done ──

def _read_sse_events(url, max_events=20, timeout=15):
    events = []
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        cur_event = None
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                cur_event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                payload = line[len("data: "):]
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    obj = payload
                events.append((cur_event, obj))
                if cur_event == "done" or len(events) >= max_events:
                    break
    return events


def test_term_stream2_sse_carries_output_and_terminates(env):
    """term_stream2 (auth OFF here) streams the stub's echoed bytes and ENDS with
    a done event when the session is killed (dead). Never hangs."""
    import anchor_gui
    import paths
    env["monkeypatch"].delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)
    gui = importlib.reload(anchor_gui)
    ts = env["ts"]
    rec = ts.start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    ts.input(sid, "SSE-ECHO-BYTES")

    server, port, t = _serve(gui)
    try:
        # Kill the session shortly after the stream opens so it transitions to
        # 'dead' and the stream emits a terminal done (proves termination).
        def _kill_soon():
            import time as _t
            _t.sleep(0.15)
            ts.kill(sid)
        killer = threading.Thread(target=_kill_soon, daemon=True)
        killer.start()
        url = (f"http://127.0.0.1:{port}/api/rnd/term_stream2?session={sid}"
               f"&poll=0.02&max_ticks=200&hb=3")
        events = _read_sse_events(url, max_events=40, timeout=15)
        killer.join(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)

    names = [e for e, _ in events]
    assert events, "no SSE events received"
    # The echoed bytes were delivered over the stream.
    texts = "".join(obj.get("text", "") for ev, obj in events
                    if ev == "output" and isinstance(obj, dict))
    assert "SSE-ECHO-BYTES" in texts
    # The stream TERMINATED cleanly with a done event (no hang).
    assert "done" in names
