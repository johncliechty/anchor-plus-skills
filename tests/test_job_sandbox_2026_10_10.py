"""Offline check preparation boundaries, plus an opt-in native non-model probe."""
from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

import job_sandbox as sandbox


@pytest.fixture
def layout(tmp_path):
    source = tmp_path / "author files"
    owned = tmp_path / "parent control"
    runtime = tmp_path / "trusted runtime"
    for folder in (source, owned, runtime):
        folder.mkdir()
    executable = runtime / "runtime.exe"
    executable.write_bytes(b"test-only executable placeholder")
    codex = runtime / "codex.exe"
    codex.write_bytes(b"test-only launcher placeholder")
    (source / "changed.py").write_text("print('uncommitted author change')\n")
    (source / "new.py").write_text("print('not in HEAD')\n")
    (source / "empty").mkdir()
    for name in (".git", ".ecgberht"):
        (source / name).mkdir()
        (source / name / "private").write_text("must not be copied")
    return source, owned, runtime, executable, codex


def prepare(layout, **overrides):
    source, owned, runtime, executable, codex = layout
    kwargs = dict(owned_base=owned, trusted_codex=codex,
                  trusted_runtime_roots=(runtime,))
    kwargs.update(overrides)
    return sandbox.prepare_check(source, [str(executable), "new.py"], **kwargs)


def test_snapshot_current_author_files_and_never_copy_check_mutations_back(layout):
    source, _owned, _runtime, _executable, _codex = layout
    with prepare(layout) as job:
        assert (job.workspace / "new.py").read_bytes() == (source / "new.py").read_bytes()
        assert (job.workspace / "changed.py").read_bytes() == (source / "changed.py").read_bytes()
        assert (job.workspace / "empty").is_dir()
        assert not (job.workspace / ".git").exists()
        assert not (job.workspace / ".ecgberht").exists()
        (job.workspace / "changed.py").write_text("check mutation")
        (job.workspace / "check-output.txt").write_text("generated")
        assert job.verify_source_unchanged() is True
        assert "uncommitted" in (source / "changed.py").read_text()
        assert not (source / "check-output.txt").exists()
        root = job.root
    assert not root.exists()


@pytest.mark.parametrize("change", ["bytes", "new", "delete", "empty-directory"])
def test_commit_guard_detects_original_source_drift(layout, change):
    source = layout[0]
    with prepare(layout) as job:
        if change == "bytes":
            (source / "new.py").write_text("externally changed")
        elif change == "new":
            (source / "arrived.py").write_text("new external author file")
        elif change == "delete":
            (source / "changed.py").unlink()
        else:
            (source / "new empty directory").mkdir()
        with pytest.raises(sandbox.SandboxError, match="source changed"):
            job.verify_source_unchanged()


def test_fingerprint_is_deterministic_across_private_directories(layout):
    with prepare(layout) as first, prepare(layout) as second:
        assert first.workspace != second.workspace
        assert first.source_fingerprint == second.source_fingerprint


def test_network_policy_control_separation_and_clean_environment(layout, monkeypatch):
    for key in ("ANCHOR_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY",
                "NODE_OPTIONS", "NODE_PATH", "PYTHONSTARTUP", "PYTHONPATH",
                "GIT_CONFIG_GLOBAL", "RIPGREP_CONFIG_PATH", "HTTP_PROXY",
                "CODEX_HOME", "CODEX_WINDOWS_MXC_PAYLOAD"):
        monkeypatch.setenv(key, "POISONED")
    monkeypatch.setenv("PATH", str(layout[0]))
    with prepare(layout) as job:
        import tomllib
        config = tomllib.loads((job.control / "config.toml").read_text())
        profile = config["permissions"]["anchor-job"]
        assert config["windows"]["sandbox"] == "mxc"
        assert profile["network"] == {"enabled": False}
        assert profile["filesystem"][':workspace_roots'] == {".": "write"}
        assert profile["filesystem"][layout[2].as_posix()] == {".": "read"}
        assert job.control not in job.workspace.parents
        assert job.workspace not in job.control.parents
        assert all(value != "POISONED" for value in job.env.values())
        assert job.env["CODEX_HOME"] == str(job.control)
        assert Path(job.env["TEMP"]).parent == job.workspace
        assert job.env["TMP"] == job.env["TEMP"]
        assert str(layout[0]) not in job.env["PATH"].split(os.pathsep)
        assert "permissions.anchor-job.network.enabled=false" in job.argv
        assert job.argv[job.argv.index("--") + 1:] == (str(layout[3]), "new.py")
        assert not job.receipt["confinement_verified"]
        assert json.loads((job.control / "preparation.json").read_text()) == job.receipt
        with pytest.raises(TypeError):
            job.env["ANCHOR_TOKEN"] = "cannot mutate"
        with pytest.raises(FrozenInstanceError):
            job.argv = ("unconfined",)


def test_extra_script_with_spaces_remaps_exactly_and_source_paths_use_snapshot(layout, tmp_path):
    source, owned, runtime, executable, codex = layout
    external = tmp_path / "parent check with spaces.py"
    external.write_text("print('trusted external check')")
    original = [str(executable), str(external), str(source / "new.py"),
                "--label=" + str(external)]
    with sandbox.prepare_check(source, original, owned_base=owned, trusted_codex=codex,
                               trusted_runtime_roots=(runtime,), extra_inputs=(external,)) as job:
        inner = job.argv[job.argv.index("--") + 1:]
        assert Path(inner[1]).read_bytes() == external.read_bytes()
        assert job.workspace in Path(inner[1]).parents
        assert inner[2] == str(job.workspace / "new.py")
        assert inner[3] == "--label=" + str(external)
        assert original[1] == str(external)


@pytest.mark.parametrize("kind", ["directory", "hardlink", "oversized", "not-in-argv"])
def test_reject_nonplain_or_unbounded_extra_and_remove_failed_preparation(layout, tmp_path, kind):
    source, owned, runtime, executable, codex = layout
    extra = tmp_path / "extra"
    if kind == "directory":
        extra.mkdir()
    elif kind == "hardlink":
        target = tmp_path / "target"
        target.write_text("outside")
        os.link(target, extra)
    else:
        extra.write_bytes(b"x")
        if kind == "oversized":
            with extra.open("wb") as writer:
                writer.truncate(8 * 1024 * 1024 + 1)
    argv = [str(executable), "new.py" if kind == "not-in-argv" else str(extra)]
    with pytest.raises(sandbox.SandboxError):
        sandbox.prepare_check(source, argv, owned_base=owned, trusted_codex=codex,
                              trusted_runtime_roots=(runtime,), extra_inputs=(extra,))
    assert list(owned.iterdir()) == []


def test_reject_source_hardlink_before_copying_outside_bytes(layout, tmp_path):
    outside = tmp_path / "outside-canary"
    outside.write_text("secret synthetic canary")
    os.link(outside, layout[0] / "linked.txt")
    with pytest.raises(sandbox.SandboxError, match="hard link"):
        prepare(layout)
    assert outside.read_text() == "secret synthetic canary"
    assert list(layout[1].iterdir()) == []


def directory_link(target, link):
    if os.name == "nt":
        # A junction needs no developer-mode symlink privilege; these are owned
        # disposable test paths, passed as separate arguments to a fixed command.
        result = subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            pytest.skip("cannot create an owned junction on this test host")
    else:
        link.symlink_to(target, target_is_directory=True)


def test_reject_directory_escape_and_cleanup_does_not_traverse_link(layout, tmp_path):
    outside = tmp_path / "unrelated"
    outside.mkdir()
    canary = outside / "preserve.txt"
    canary.write_text("unchanged")
    escape = layout[0] / "escape"
    directory_link(outside, escape)
    try:
        with pytest.raises(sandbox.SandboxError, match="reparse"):
            prepare(layout)
        assert list(layout[1].iterdir()) == []
    finally:
        if os.name == "nt":
            escape.rmdir()
        else:
            escape.unlink()
    job = prepare(layout)
    directory_link(outside, job.workspace / "check-created-link")
    job.cleanup()
    assert canary.read_text() == "unchanged"
    assert not job.root.exists()


@pytest.mark.parametrize("overlap", ["same", "owned-under-source", "source-under-owned"])
def test_disallow_overlapping_source_and_control(layout, overlap):
    source, owned, _runtime, _executable, _codex = layout
    if overlap == "same":
        owned = source
    elif overlap == "owned-under-source":
        owned = source / "control"
        owned.mkdir()
    else:
        owned = source.parent
    with pytest.raises(sandbox.SandboxError, match="overlap"):
        prepare(layout, owned_base=owned)


@pytest.mark.parametrize("root_kind", ["source", "control", "broad-parent"])
def test_read_roots_cannot_expose_source_or_private_control(layout, root_kind):
    roots = {"source": layout[0], "control": layout[1], "broad-parent": layout[0].parent}
    with pytest.raises(sandbox.SandboxError, match="read grant"):
        prepare(layout, trusted_runtime_roots=(roots[root_kind],))


def test_refuse_untrusted_launcher_configuration(layout):
    source = layout[0]
    (source / ".codex").mkdir()
    (source / ".codex" / "config.toml").write_text('[windows]\nsandbox="unelevated"')
    with pytest.raises(sandbox.SandboxError, match="job-local Codex"):
        prepare(layout)
    assert not list(layout[1].iterdir())


def test_cleanup_refuses_a_different_directory_even_with_similar_name(layout, tmp_path):
    job = prepare(layout)
    outside = tmp_path / "anchor-check-outside"
    outside.mkdir()
    (outside / "keep").write_text("do not delete")
    try:
        fake = replace(job, root=outside)
        with pytest.raises(sandbox.SandboxError, match="outside"):
            fake.cleanup()
        assert (outside / "keep").read_text() == "do not delete"
    finally:
        job.cleanup()


def test_restricted_author_policy_has_no_execution_network_or_bypass_tools(layout):
    flags = sandbox.restricted_claude_flags()
    assert flags[flags.index("--tools") + 1].split(",") == ["Read", "Glob", "Grep", "Edit", "Write"]
    for required in ("--restricted", "--safe-mode", "--strict-mcp-config"):
        assert required in flags
    assert "--bare" not in flags
    assert "--dangerously-skip-permissions" not in flags
    env = sandbox.clean_environment(
        {"USERPROFILE": "normal-subscription-profile", "ANCHOR_TOKEN": "secret",
         "ANTHROPIC_API_KEY": "secret", "NODE_OPTIONS": "--require malicious.js"},
        runtime_paths=(layout[2],),
    )
    assert env["USERPROFILE"] == "normal-subscription-profile"
    assert set(env) == {"USERPROFILE", "PATH"}


@pytest.mark.skipif(os.name != "nt" or os.environ.get("ANCHOR_TEST_MXC") != "1",
                    reason="opt-in installed native MXC non-model probe")
def test_actual_mxc_captured_child_and_filesystem_network_canaries(tmp_path):
    """No model, credentials, service API or real campaign is touched."""
    codex_name = shutil.which("codex.exe")
    assert codex_name, "native probe requires the installed Codex executable"
    codex = Path(codex_name).resolve()
    python = Path(sys.executable).resolve()
    source, owned = tmp_path / "source", tmp_path / "owned"
    source.mkdir()
    owned.mkdir()
    canary = tmp_path / "outside.txt"
    canary.write_text("UNCHANGED")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            connection, _ = listener.accept()
            connection.close()
        code = '''import json, pathlib, socket, subprocess, sys
r = {}
child = subprocess.run([sys.executable, '-c', "print('CAPTURED_CHILD_OK')"],
                       capture_output=True, text=True, timeout=5)
r['child'] = [child.returncode, child.stdout.strip()]
pathlib.Path('created.txt').write_text('OWN')
for name, action in [('read', lambda: pathlib.Path(sys.argv[1]).read_bytes()),
                     ('write', lambda: pathlib.Path(sys.argv[1]).write_text('ESCAPE'))]:
    try: action(); r[name] = 'unexpected-success'
    except OSError as e: r[name] = [e.errno, getattr(e, 'winerror', None)]
try:
    with socket.create_connection(('127.0.0.1', int(sys.argv[2])), timeout=2):
        r['network'] = 'unexpected-success'
except OSError as e: r['network'] = [e.errno, getattr(e, 'winerror', None)]
pathlib.Path('result.json').write_text(json.dumps(r))
'''
        (source / "probe.py").write_text(code)
        with sandbox.prepare_check(
            source, [str(python), "probe.py", str(canary), str(port)],
            owned_base=owned, trusted_codex=codex,
            trusted_runtime_roots=(python.parent,),
        ) as job:
            run = subprocess.run(job.argv, cwd=job.cwd, env=dict(job.env),
                                 capture_output=True, text=True, timeout=30,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            assert run.returncode == 0, run.stderr[-3000:]
            receipt = json.loads((job.workspace / "result.json").read_text())
            assert receipt["child"] == [0, "CAPTURED_CHILD_OK"]
            for operation in ("read", "write"):
                assert isinstance(receipt[operation], list)
                assert receipt[operation][0] in (1, 13)
            assert isinstance(receipt["network"], list)
            assert 10013 in receipt["network"] or 13 in receipt["network"]
            assert canary.read_text() == "UNCHANGED"
            assert (job.workspace / "created.txt").read_text() == "OWN"
            assert job.verify_source_unchanged()
            assert not (source / "created.txt").exists()
