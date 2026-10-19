"""service_bootstrap — the thin NSSM entry wrapper (2026-10-10).

Every fixture here is SYNTHETIC (a tmp_path file with a sentinel "secret").
No test reads the real service environment, the registry or a real
credential, and no test starts a host process: an autouse guard turns
``runpy.run_path`` and the process-spawning seams into assertion failures
for the duration of each test, and the wrapper is always driven through an
injected recording runner.
"""

import io
import json
import os
import re
import runpy
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

import service_bootstrap as sb

FLAG = sb.ENVIRONMENT_FILE_FLAG
SECRET = "SENTINEL-SECRET-VALUE-9f2a7c"
DATA_VALUE = "SENTINEL-DATA-DIR-VALUE-41b0"
SENTINELS = (SECRET, DATA_VALUE)


# ── Guards + helpers ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_host_process(monkeypatch):
    """Any attempt to run the real target or spawn a process FAILS the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("a test must never start a host process")

    monkeypatch.setattr(runpy, "run_path", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(os, "system", refuse)
    for name in ("execv", "execve", "spawnv", "spawnve", "startfile"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, refuse)
    yield


class FakeStat(object):
    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


def write_env(tmp_path, environment=None, *, raw=None, schema=sb.SCHEMA_ID,
              extra=None, name="service-env.json"):
    """Write a synthetic environment file; return its NORMALIZED path string."""
    target = tmp_path / name
    if raw is None:
        doc = {"schema": schema,
               "environment": {"ANCHOR_TOKEN": SECRET} if environment is None else environment}
        if extra:
            doc.update(extra)
        raw = json.dumps(doc)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    target.write_bytes(raw)
    return os.path.normpath(str(target))


def assert_clean(text):
    for sentinel in SENTINELS:
        assert sentinel not in text, "a value leaked into a diagnostic"


def run_main(argv, environ=None, runner=None, **kwargs):
    environ = {} if environ is None else environ
    calls = []

    def record(target, forwarded):
        calls.append((target, list(forwarded)))

    out, err = io.StringIO(), io.StringIO()
    rc = sb.main(argv, environ=environ, runner=runner or record, stdout=out, stderr=err, **kwargs)
    return SimpleNamespace(rc=rc, calls=calls, environ=environ, out=out.getvalue(), err=err.getvalue())


def expect_refusal(argv, code, environ=None):
    """The wrapper must refuse BEFORE the runner, apply nothing, name the code
    and never echo a value."""
    environ = {} if environ is None else environ
    before = dict(environ)
    result = run_main(argv, environ=environ)
    assert result.rc == sb.EXIT_BOOTSTRAP_ERROR
    assert result.calls == [], "refused configurations must never reach the runner"
    assert result.environ == before, "a refused configuration must apply nothing"
    assert result.err.startswith(sb.REFUSED_PREFIX + code + ":"), result.err
    if argv and argv[0] == "--check":
        assert json.loads(result.out)["ok"] is False
    else:
        assert result.out == ""
    assert_clean(result.err)
    assert_clean(result.out)
    # The same refusal through the pure diagnostic surface.
    report = sb.diagnose(argv)
    assert report["ok"] is False and report["code"] == code
    assert_clean(json.dumps(report))
    return result


def expected_target():
    return os.path.join(os.path.dirname(os.path.abspath(sb.__file__)), "anchor_gui.py")


# ── Happy path: environment applied, arguments forwarded, fixed target ─────

def test_valid_file_applies_map_then_forwards_args_to_the_fixed_target(tmp_path):
    path = write_env(tmp_path, {"ANCHOR_TOKEN": SECRET, "ANCHOR_DATA_DIR": DATA_VALUE})
    environ = {"PATH": "keep-me", "USERPROFILE": "keep-too",
               "ANCHOR_TOKEN": "old-registry-token", "ANCHOR_FRONTEND": "static"}
    seen = {}

    def runner(target, forwarded):
        # Ordering: the map is already in the environment when the target runs.
        seen["target"] = target
        seen["forwarded"] = list(forwarded)
        seen["token_at_run"] = environ.get("ANCHOR_TOKEN")

    result = run_main([FLAG, path, "--no-browser", "--port", "8777"], environ=environ, runner=runner)
    assert result.rc == 0
    assert seen["target"] == expected_target()
    assert seen["forwarded"] == ["--no-browser", "--port", "8777"]
    assert seen["token_at_run"] == SECRET
    # File wins for the names it supplies ...
    assert environ["ANCHOR_TOKEN"] == SECRET
    assert environ["ANCHOR_DATA_DIR"] == DATA_VALUE
    # ... and every unrelated entry is preserved verbatim.
    assert environ["PATH"] == "keep-me"
    assert environ["USERPROFILE"] == "keep-too"
    assert environ["ANCHOR_FRONTEND"] == "static"
    assert set(environ) == {"PATH", "USERPROFILE", "ANCHOR_TOKEN", "ANCHOR_FRONTEND", "ANCHOR_DATA_DIR"}
    # The success path prints nothing — and certainly no value.
    assert result.out == "" and result.err == ""


def test_main_reads_sys_argv_by_default(tmp_path, monkeypatch):
    path = write_env(tmp_path)
    calls = []
    monkeypatch.setattr(sys, "argv", ["service_bootstrap.py", FLAG, path, "--no-browser"])
    rc = sb.main(environ={}, runner=lambda target, forwarded: calls.append((target, list(forwarded))))
    assert rc == 0
    assert calls == [(expected_target(), ["--no-browser"])]


def test_forwarded_arguments_are_verbatim_and_never_interpreted(tmp_path):
    path = write_env(tmp_path)
    forwarded = ["--no-browser", "--port", "8777", "--future-flag", "value", "positional"]
    result = run_main([FLAG, path] + forwarded)
    assert result.rc == 0
    assert result.calls == [(expected_target(), forwarded)]


def test_lexical_normalization_never_follows_links(tmp_path):
    path = write_env(tmp_path)
    (tmp_path / "sub").mkdir()
    dotted = os.path.join(str(tmp_path), "sub", "..", "service-env.json")
    result = run_main([FLAG, dotted])
    assert result.rc == 0
    assert sb.normalize_environment_path(dotted) == path
    if os.name == "nt":
        assert sb.normalize_environment_path(path.replace("\\", "/")) == path


def test_precedence_explicit_file_wins_only_for_supplied_names():
    environ = {"A": "1", "B": "2", "ANCHOR_TOKEN": "registry"}
    applied = sb.apply_environment({"B": "file", "ANCHOR_TOKEN": SECRET}, environ)
    assert applied == ["ANCHOR_TOKEN", "B"]
    assert environ == {"A": "1", "B": "file", "ANCHOR_TOKEN": SECRET}


def test_apply_environment_is_defensive_about_nul_and_types():
    with pytest.raises(sb.BootstrapError) as info:
        sb.apply_environment({"A": "x\x00y"}, {})
    assert info.value.code == "nul"
    with pytest.raises(sb.BootstrapError) as info:
        sb.apply_environment({"A": 1}, {})
    assert info.value.code == "shape"


# ── No arbitrary target / substitution ─────────────────────────────────────

def test_target_is_the_fixed_sibling_regardless_of_arguments_or_environment(tmp_path, monkeypatch):
    path = write_env(tmp_path, {
        "ANCHOR_TOKEN": SECRET,
        "ANCHOR_BOOTSTRAP_TARGET": str(tmp_path / "evil.py"),
        "PYTHONPATH": str(tmp_path),
    })
    (tmp_path / "evil.py").write_text("raise SystemExit('never')", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_BOOTSTRAP_TARGET", str(tmp_path / "evil.py"))
    forwarded = [str(tmp_path / "evil.py"), "-m", "evil", "--target", str(tmp_path / "evil.py"), "-c", "pass"]
    result = run_main([FLAG, path] + forwarded)
    assert result.rc == 0
    assert result.calls == [(expected_target(), forwarded)]
    assert sb.target_path() == expected_target()
    assert os.path.basename(sb.target_path()) == sb.TARGET_NAME


def test_second_environment_file_flag_is_refused_before_the_runner(tmp_path):
    path = write_env(tmp_path)
    other = write_env(tmp_path, name="other.json")
    expect_refusal([FLAG, path, "--no-browser", FLAG, other], "usage")
    expect_refusal([FLAG, path, FLAG + "=" + other], "usage")
    expect_refusal([FLAG, path, "--check"], "usage")


@pytest.mark.parametrize("argv", [
    [],
    ["--no-browser"],
    [FLAG],
    [FLAG, ""],
    [FLAG, "   "],
    ["--check"],
    ["--no-browser", FLAG, "C:\\x.json" if os.name == "nt" else "/x.json"],
])
def test_missing_or_misplaced_flag_is_refused(argv):
    expect_refusal(argv, "usage")


def test_environment_file_argument_with_equals_form_is_refused(tmp_path):
    path = write_env(tmp_path)
    expect_refusal([FLAG + "=" + path], "usage")


def test_nul_in_an_argument_is_refused(tmp_path):
    path = write_env(tmp_path)
    expect_refusal([FLAG, path, "--no\x00browser"], "usage")


# ── Path rules ─────────────────────────────────────────────────────────────

def test_relative_path_is_refused():
    expect_refusal([FLAG, os.path.join("relative", "service-env.json")], "path")


@pytest.mark.parametrize("raw", [
    "\\\\?\\C:\\Anchor\\service-env.json",
    "\\\\.\\C:\\Anchor\\service-env.json",
    "\\\\server\\share\\service-env.json",
])
def test_verbatim_prefixes_and_unc_paths_are_refused(raw):
    with pytest.raises(sb.BootstrapError) as info:
        sb.normalize_environment_path(raw)
    assert info.value.code == "path"


@pytest.mark.skipif(os.name != "nt", reason="drive-relative paths exist only on Windows")
def test_drive_relative_and_rootless_paths_are_refused_on_windows():
    for raw in ("C:service-env.json", "\\Anchor\\service-env.json"):
        with pytest.raises(sb.BootstrapError) as info:
            sb.normalize_environment_path(raw)
        assert info.value.code == "path"


def test_missing_file_is_refused_with_the_normalized_path_in_the_diagnostic(tmp_path):
    missing = os.path.join(str(tmp_path), "nope", "..", "absent.json")
    result = expect_refusal([FLAG, missing], "missing")
    assert os.path.normpath(missing) in result.err


def test_directory_path_is_refused(tmp_path):
    expect_refusal([FLAG, str(tmp_path)], "not-a-file")


def test_unreadable_file_is_refused_without_echoing_anything(tmp_path, monkeypatch):
    path = write_env(tmp_path)
    real_open = os.open

    def denied(target, *args, **kwargs):
        if os.path.normcase(str(target)) == os.path.normcase(path):
            raise PermissionError(13, "denied")
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr(os, "open", denied)
    expect_refusal([FLAG, path], "unreadable")


# ── Link / reparse coherence ───────────────────────────────────────────────

def test_symlink_to_a_real_file_is_refused(tmp_path):
    path = write_env(tmp_path)
    link = tmp_path / "link.json"
    try:
        os.symlink(path, str(link))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlink creation is not permitted on this host")
    expect_refusal([FLAG, str(link)], "link")


def test_reparse_point_attribute_is_refused_even_when_not_a_symlink(tmp_path, monkeypatch):
    path = write_env(tmp_path)
    real_lstat = os.lstat

    def junction_like(target, *args, **kwargs):
        if os.path.normcase(str(target)) == os.path.normcase(path):
            return FakeStat(st_mode=stat.S_IFREG | 0o644, st_file_attributes=0x400,
                            st_reparse_tag=0xA0000003, st_size=16, st_dev=7, st_ino=9)
        return real_lstat(target, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", junction_like)
    expect_refusal([FLAG, path], "link")


def test_link_in_an_ancestor_is_refused_via_canonical_mismatch(tmp_path, monkeypatch):
    path = write_env(tmp_path)
    elsewhere = os.path.join(str(tmp_path), "real-location", "service-env.json")
    real_realpath = os.path.realpath

    def through_a_junction(target, *args, **kwargs):
        if os.path.normcase(str(target)) == os.path.normcase(path):
            return elsewhere
        return real_realpath(target, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", through_a_junction)
    result = expect_refusal([FLAG, path], "link")
    assert elsewhere in result.err  # the canonical path is a safe diagnostic


def test_identity_change_between_inspection_and_open_is_refused(tmp_path, monkeypatch):
    path = write_env(tmp_path)
    size = os.path.getsize(path)
    real_lstat, real_fstat = os.lstat, os.fstat

    def inspected(target, *args, **kwargs):
        if os.path.normcase(str(target)) == os.path.normcase(path):
            return FakeStat(st_mode=stat.S_IFREG | 0o644, st_size=size, st_dev=7, st_ino=9)
        return real_lstat(target, *args, **kwargs)

    def opened(fd):
        st = real_fstat(fd)
        return FakeStat(st_mode=st.st_mode, st_size=st.st_size, st_dev=7, st_ino=10)

    monkeypatch.setattr(os, "lstat", inspected)
    monkeypatch.setattr(os, "fstat", opened)
    expect_refusal([FLAG, path], "link")


def test_diagnostics_never_claim_acl_protection(tmp_path):
    path = write_env(tmp_path)
    facts = sb.inspect_environment_file(path)
    assert set(facts) == {"path", "canonical", "size", "identity"}
    report = sb.diagnose([FLAG, path])
    assert not any("acl" in key.lower() or "protect" in key.lower() for key in report)


# ── Document validation ────────────────────────────────────────────────────

def test_invalid_json_is_refused_and_the_content_is_never_echoed(tmp_path):
    path = write_env(tmp_path, raw='{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s"' % (sb.SCHEMA_ID, SECRET))
    result = expect_refusal([FLAG, path], "invalid-json")
    assert "line" in result.err and "column" in result.err


def test_non_utf8_file_is_refused(tmp_path):
    path = write_env(tmp_path, raw=b'{"schema": "\xff\xfe", "environment": {"ANCHOR_TOKEN": "' + SECRET.encode() + b'"}}')
    expect_refusal([FLAG, path], "encoding")


def test_utf8_bom_is_tolerated(tmp_path):
    body = json.dumps({"schema": sb.SCHEMA_ID, "environment": {"ANCHOR_TOKEN": SECRET}})
    path = write_env(tmp_path, raw=b"\xef\xbb\xbf" + body.encode("utf-8"))
    assert run_main([FLAG, path]).rc == 0


ENV_OK = '{"ANCHOR_TOKEN": "%s"}' % SECRET
SHAPES = [
    ("top-level list", '[{"ANCHOR_TOKEN": "%s"}]' % SECRET, "shape"),
    ("top-level string", '"%s"' % SECRET, "shape"),
    ("missing environment", '{"schema": "%s"}' % sb.SCHEMA_ID, "shape"),
    ("missing schema", '{"environment": %s}' % ENV_OK, "shape"),
    ("wrong schema", '{"schema": "%s", "environment": %s}' % (SECRET, ENV_OK), "schema"),
    ("schema not a string", '{"schema": 1, "environment": %s}' % ENV_OK, "schema"),
    ("unknown top-level key", '{"schema": "%s", "environment": %s, "%s": "x"}' % (sb.SCHEMA_ID, ENV_OK, SECRET), "shape"),
    ("duplicate top-level key", '{"schema": "%s", "schema": "%s", "environment": %s}' % (sb.SCHEMA_ID, sb.SCHEMA_ID, ENV_OK), "shape"),
    ("environment is a list", '{"schema": "%s", "environment": ["%s"]}' % (sb.SCHEMA_ID, SECRET), "shape"),
    ("environment is a string", '{"schema": "%s", "environment": "%s"}' % (sb.SCHEMA_ID, SECRET), "shape"),
    ("environment is empty", '{"schema": "%s", "environment": {}}' % sb.SCHEMA_ID, "shape"),
    ("value is a number", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "PORT": 8777}}' % (sb.SCHEMA_ID, SECRET), "shape"),
    ("value is null", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "X": null}}' % (sb.SCHEMA_ID, SECRET), "shape"),
    ("value is a boolean", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "X": true}}' % (sb.SCHEMA_ID, SECRET), "shape"),
    ("value is a list", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": ["%s"]}}' % (sb.SCHEMA_ID, SECRET), "shape"),
    ("value is an object", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": {"nested": "%s"}}}' % (sb.SCHEMA_ID, SECRET), "shape"),
]


@pytest.mark.parametrize("label,raw,code", SHAPES, ids=[item[0] for item in SHAPES])
def test_invalid_shapes_are_refused_before_the_runner(tmp_path, label, raw, code):
    path = write_env(tmp_path, raw=raw)
    expect_refusal([FLAG, path], code)


def test_oversize_file_is_refused_before_it_is_parsed(tmp_path, monkeypatch):
    path = write_env(tmp_path, {"ANCHOR_TOKEN": SECRET, "PAD": "x" * (sb.MAX_FILE_BYTES + 16)})
    assert os.path.getsize(path) > sb.MAX_FILE_BYTES
    monkeypatch.setattr(sb, "parse_environment_document",
                        lambda *a, **k: pytest.fail("an oversize file must never be parsed"))
    result = expect_refusal([FLAG, path], "oversize")
    assert "x" * 64 not in result.err


def test_oversize_value_is_refused_and_named_without_its_content(tmp_path):
    path = write_env(tmp_path, {"ANCHOR_TOKEN": SECRET, "PAD": "y" * (sb.MAX_VALUE_CHARS + 1)})
    result = expect_refusal([FLAG, path], "oversize")
    assert "'PAD'" in result.err and "y" * 64 not in result.err


def test_too_many_entries_is_refused(tmp_path):
    environment = {"ANCHOR_TOKEN": SECRET}
    for index in range(sb.MAX_ENTRIES):
        environment["VAR_%d" % index] = "v"
    path = write_env(tmp_path, environment)
    expect_refusal([FLAG, path], "oversize")


@pytest.mark.parametrize("bad", [
    "", "1ABC", "A-B", "A B", "A=B", "ANCHOR.TOKEN", "\u00c4NCHOR", "A\tB", "A\nB",
    "x" * (sb.MAX_NAME_CHARS + 1), SECRET,
])
def test_invalid_names_are_refused_and_reported_by_position_only(tmp_path, bad):
    path = write_env(tmp_path, {"ANCHOR_TOKEN": SECRET, bad: DATA_VALUE})
    result = expect_refusal([FLAG, path], "invalid-name")
    assert "entry 2" in result.err
    if bad.strip():
        assert bad not in result.err


@pytest.mark.parametrize("label,raw", [
    ("nul in a value", json.dumps({"schema": sb.SCHEMA_ID, "environment": {"ANCHOR_TOKEN": SECRET, "X": "a\x00" + DATA_VALUE}})),
    ("nul in a name", json.dumps({"schema": sb.SCHEMA_ID, "environment": {"ANCHOR_TOKEN": SECRET, "X\x00Y": DATA_VALUE}})),
    ("raw nul byte in the file", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s\x00"}}' % (sb.SCHEMA_ID, SECRET)),
])
def test_nul_anywhere_is_refused(tmp_path, label, raw):
    path = write_env(tmp_path, raw=raw)
    expect_refusal([FLAG, path], "nul")


@pytest.mark.parametrize("label,raw", [
    ("exact duplicate", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "ANCHOR_TOKEN": "%s"}}' % (sb.SCHEMA_ID, SECRET, DATA_VALUE)),
    ("case variant", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "Anchor_Token": "%s"}}' % (sb.SCHEMA_ID, SECRET, DATA_VALUE)),
    ("case variant of another name", '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "Path": "a", "PATH": "b"}}' % (sb.SCHEMA_ID, SECRET)),
])
def test_duplicate_names_are_refused_case_insensitively(tmp_path, label, raw):
    path = write_env(tmp_path, raw=raw)
    expect_refusal([FLAG, path], "duplicate-name")


@pytest.mark.parametrize("environment", [
    {"ANCHOR_DATA_DIR": DATA_VALUE},
    {"ANCHOR_TOKEN": ""},
    {"ANCHOR_TOKEN": "   \t"},
    {"anchor_token": SECRET},
])
def test_absent_or_blank_token_is_refused_no_auth_disabled_fallback(tmp_path, environment):
    path = write_env(tmp_path, environment)
    expect_refusal([FLAG, path], "missing-required")


def test_parse_environment_document_returns_only_the_supplied_names():
    raw = json.dumps({"schema": sb.SCHEMA_ID, "environment": {"ANCHOR_TOKEN": SECRET, "B": "2"}}).encode("utf-8")
    assert sb.parse_environment_document(raw) == {"ANCHOR_TOKEN": SECRET, "B": "2"}


# ── Safe diagnostics + --check ─────────────────────────────────────────────

def test_check_reports_names_never_values_and_applies_or_runs_nothing(tmp_path):
    path = write_env(tmp_path, {"ANCHOR_TOKEN": SECRET, "ANCHOR_DATA_DIR": DATA_VALUE})
    environ = {"PATH": "keep-me"}
    out, err = io.StringIO(), io.StringIO()
    rc = sb.main(["--check", FLAG, path, "--no-browser"], environ=environ, stdout=out, stderr=err)
    assert rc == 0 and err.getvalue() == ""
    assert environ == {"PATH": "keep-me"}
    report = json.loads(out.getvalue())
    assert report == {
        "ok": True, "code": None, "reason": None, "path": path,
        "size": os.path.getsize(path), "entry_count": 2,
        "names": ["ANCHOR_DATA_DIR", "ANCHOR_TOKEN"],
        "target": expected_target(), "forwarded": ["--no-browser"],
    }
    assert_clean(out.getvalue())
    assert sb.diagnose(["--check", FLAG, path, "--no-browser"]) == report
    assert sb.diagnose([FLAG, path, "--no-browser"]) == report


def test_check_failure_reports_the_code_and_the_normalized_path(tmp_path):
    missing = os.path.join(str(tmp_path), "absent.json")
    out, err = io.StringIO(), io.StringIO()
    rc = sb.main(["--check", FLAG, missing], environ={}, stdout=out, stderr=err)
    assert rc == sb.EXIT_BOOTSTRAP_ERROR
    assert err.getvalue().startswith(sb.REFUSED_PREFIX + "missing:")
    report = json.loads(out.getvalue())
    assert report == {"ok": False, "code": "missing", "path": os.path.normpath(missing),
                      "reason": "the environment file does not exist"}


def test_unexpected_exceptions_are_reported_by_type_name_only(tmp_path, monkeypatch):
    path = write_env(tmp_path)

    def explode(*args, **kwargs):
        raise RuntimeError("stack text containing " + SECRET)

    monkeypatch.setattr(sb, "parse_environment_document", explode)
    result = expect_refusal([FLAG, path], "internal")
    assert "RuntimeError" in result.err


def test_bootstrap_error_text_carries_only_safe_fields():
    exc = sb.BootstrapError("missing", "the environment file does not exist", "C:\\x\\service-env.json")
    assert str(exc) == "missing: the environment file does not exist [environment file: C:\\x\\service-env.json]"
    assert (exc.code, exc.reason, exc.path) == ("missing", "the environment file does not exist", "C:\\x\\service-env.json")
    assert str(sb.BootstrapError("usage", sb.USAGE)) == "usage: " + sb.USAGE


def test_streams_may_be_absent_as_under_pythonw(tmp_path):
    missing = os.path.join(str(tmp_path), "absent.json")
    assert sb.main([FLAG, missing], environ={}, runner=lambda *a: None,
                   stdout=io.StringIO(), stderr=None) == sb.EXIT_BOOTSTRAP_ERROR


# ── The default runner (runpy, injected recorder — the real target never runs)

def test_default_runner_runs_the_fixed_target_as_main_with_forwarded_argv(monkeypatch):
    seen = {}

    def fake_run_path(path_name, init_globals=None, run_name=None):
        seen["path"] = path_name
        seen["run_name"] = run_name
        seen["argv"] = list(sys.argv)
        seen["dir_on_path"] = any(
            os.path.normcase(os.path.abspath(entry or os.curdir)) == os.path.normcase(os.path.dirname(path_name))
            for entry in sys.path)
        return {}

    monkeypatch.setattr(runpy, "run_path", fake_run_path)
    monkeypatch.setattr(sys, "argv", ["service_bootstrap.py"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    target = sb.target_path()
    sb.run_anchor_gui(target, ["--no-browser", "--port", "8777"])
    assert seen == {"path": target, "run_name": "__main__",
                    "argv": [target, "--no-browser", "--port", "8777"], "dir_on_path": True}


def test_check_target_refuses_a_missing_or_linked_target(tmp_path, monkeypatch):
    with pytest.raises(sb.BootstrapError) as info:
        sb.check_target(os.path.join(str(tmp_path), "anchor_gui.py"))
    assert info.value.code == "target"
    real_lstat = os.lstat
    target = sb.target_path()

    def linked(path, *args, **kwargs):
        if os.path.normcase(str(path)) == os.path.normcase(target):
            return FakeStat(st_mode=stat.S_IFREG | 0o644, st_file_attributes=0x400, st_size=1)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", linked)
    with pytest.raises(sb.BootstrapError) as info:
        sb.check_target(target)
    assert info.value.code == "target"
    # The real sibling passes.
    monkeypatch.setattr(os, "lstat", real_lstat)
    sb.check_target(target)


# ── Static properties of the module ────────────────────────────────────────

def test_module_is_stdlib_only_imports_no_anchor_module_and_exits_through_main():
    import ast
    source = open(sb.__file__, encoding="utf-8").read()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    allowed = {"errno", "json", "os", "re", "runpy", "stat", "sys", "typing"}
    assert imported <= allowed, imported - allowed
    for forbidden in ("paths", "anchor_gui", "steward", "foundry", "pillar_flags", "winpty", "ctypes"):
        assert forbidden not in imported
    assert 'if __name__ == "__main__":\n    sys.exit(main())' in source
    # The default launch stays untouched: the wrapper never rewrites or wraps
    # anchor_gui.py itself — it only runs the adjacent file.
    assert sb.TARGET_NAME == "anchor_gui.py"


def test_no_value_ever_appears_in_any_refusal_of_a_corpus_of_bad_files(tmp_path):
    corpus = [
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "%s": "x"}}' % (sb.SCHEMA_ID, SECRET, DATA_VALUE),
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "BAD KEY": "%s"}}' % (sb.SCHEMA_ID, SECRET, DATA_VALUE),
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": 1, "X": "%s"}}' % (sb.SCHEMA_ID, DATA_VALUE),
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s"}' % (sb.SCHEMA_ID, SECRET),
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s\\u0000"}}' % (sb.SCHEMA_ID, SECRET),
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "A": "%s", "a": "%s"}}' % (sb.SCHEMA_ID, SECRET, DATA_VALUE, DATA_VALUE),
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": " "}}' % sb.SCHEMA_ID,
        '{"schema": "%s", "environment": {"ANCHOR_TOKEN": "%s", "LONG": "%s"}}' % (sb.SCHEMA_ID, SECRET, DATA_VALUE * 4000),
    ]
    for index, raw in enumerate(corpus):
        path = write_env(tmp_path, raw=raw, name="bad-%d.json" % index)
        with pytest.raises(sb.BootstrapError) as info:
            sb.load_environment_file(path)
        for text in (str(info.value), repr(info.value), info.value.code, info.value.reason, info.value.path or ""):
            assert_clean(text)
        result = run_main([FLAG, path])
        assert result.rc == sb.EXIT_BOOTSTRAP_ERROR and result.calls == [] and result.environ == {}
        assert_clean(result.err)
        assert_clean(json.dumps(sb.diagnose([FLAG, path])))
