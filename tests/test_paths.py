"""Wave 2: ANCHOR_DATA_DIR decouples data from code via the shared `paths` helper.

- With ANCHOR_DATA_DIR set to a tmp dir, every path helper resolves under it.
- With ANCHOR_DATA_DIR unset, every path helper resolves under the code dir
  (backward compatible — zero behavior change by default).
- Importing `paths` performs no directory creation; ensure_data_dirs() does.
"""
import importlib

import paths


def _reload():
    # paths reads the env var lazily per call, so no reload is needed for the
    # data-path helpers; we keep this to defend against accidental caching.
    return importlib.reload(paths)


def test_unset_resolves_under_code_dir(monkeypatch):
    monkeypatch.delenv("ANCHOR_DATA_DIR", raising=False)
    p = _reload()
    code = p.CODE_DIR
    assert p.data_dir() == code
    assert p.dashboard_md() == code / "DASHBOARD.md"
    assert p.projects_md() == code / "PROJECTS.md"
    assert p.inbox_md() == code / "INBOX.md"
    assert p.cancelled_md() == code / "CANCELLED.md"
    assert p.saved_for_later_md() == code / "SAVED_FOR_LATER.md"
    assert p.domains_dir() == code / "domains"
    assert p.logs_dir() == code / "logs"
    assert p.health_reports_dir() == code / "health_reports"
    assert p.dashboard_html() == code / "dashboard.html"


def test_set_resolves_under_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    p = _reload()
    base = tmp_path.resolve()
    assert p.data_dir() == base
    assert p.dashboard_md() == base / "DASHBOARD.md"
    assert p.projects_md() == base / "PROJECTS.md"
    assert p.inbox_md() == base / "INBOX.md"
    assert p.cancelled_md() == base / "CANCELLED.md"
    assert p.saved_for_later_md() == base / "SAVED_FOR_LATER.md"
    assert p.domains_dir() == base / "domains"
    assert p.logs_dir() == base / "logs"
    assert p.health_reports_dir() == base / "health_reports"


def test_resolution_is_lazy_per_call(monkeypatch, tmp_path):
    # Changing the env var between calls changes resolution without reload.
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path.resolve()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(other))
    assert paths.data_dir() == other.resolve()


def test_ensure_data_dirs_creates_only_when_called(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Importing/resolving does not create subdirs.
    assert not (tmp_path / "logs").exists()
    paths.ensure_data_dirs()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "domains").is_dir()
    assert (tmp_path / "health_reports").is_dir()
    # Idempotent.
    paths.ensure_data_dirs()
    assert (tmp_path / "logs").is_dir()


def test_blank_env_falls_back_to_code_dir(monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", "   ")
    assert paths.data_dir() == paths.CODE_DIR
