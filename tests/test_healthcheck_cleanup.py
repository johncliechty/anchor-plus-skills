"""Regression guard: a healthcheck run leaves NO ``__healthcheck__`` project.

Root cause this guards: the daily healthcheck registers synthetic
``__healthcheck__ rnd probe vN`` projects directly into the live
``rnd_registry.json`` and tears them down in a ``finally``. A run that was KILLED
before that teardown (or whose teardown partially failed) left the synthetic
project behind, where it rendered forever as an "ungrouped" dashboard tile.

``_cleanup_synthetic_rnd`` now does a belt-and-suspenders NAME sweep that removes
ANY ``__healthcheck__ rnd probe`` entry — including ones leaked by a prior run —
while never touching a real project (which can never start with that prefix).
"""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def hc(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import anchor_healthcheck
    importlib.reload(anchor_healthcheck)
    yield rnd_registry, anchor_healthcheck, tmp_path


def _names(rnd):
    return [e["name"] for e in rnd.list_projects(
        include_archived=True, include_future=True, include_retired=True)]


def test_cleanup_sweeps_leaked_probes_keeps_real(hc):
    rnd, hc_mod, tmp_path = hc

    # A REAL project that must survive untouched.
    real = rnd.add_project("My Real Project", str(tmp_path / "real"),
                           scaffold=False)

    # Probes LEAKED by a prior (killed) run — NOT tracked in created_ids.
    rnd.add_project(hc_mod.SYNTHETIC_RND_NAME, str(tmp_path / "p1"),
                    scaffold=False)
    rnd.add_project(hc_mod.SYNTHETIC_RND_NAME + " v9 anchor",
                    str(tmp_path / "p2"), scaffold=False)
    rnd.add_project(hc_mod.SYNTHETIC_RND_NAME + " v12",
                    str(tmp_path / "p3"), scaffold=False)

    assert sum(n.startswith(hc_mod.SYNTHETIC_RND_NAME)
               for n in _names(rnd)) == 3

    # Teardown with EMPTY created_ids — the name sweep must still remove them.
    rnd_env = {"created_ids": [], "folder": tmp_path / "throwaway",
               "v3_temp_dirs": []}
    hc_mod._cleanup_synthetic_rnd(rnd_env, hc_mod.Report())

    names = _names(rnd)
    assert not any(n.startswith(hc_mod.SYNTHETIC_RND_NAME) for n in names), \
        f"leftover healthcheck probes: {names}"
    # The real project is intact.
    assert rnd.get_project(real["id"]) is not None
    assert "My Real Project" in names


def test_cleanup_removes_tracked_probe(hc):
    rnd, hc_mod, tmp_path = hc
    proj = rnd.add_project(hc_mod.SYNTHETIC_RND_NAME, str(tmp_path / "f"),
                           scaffold=False)
    rnd_env = {"created_ids": [proj["id"]], "folder": tmp_path / "f",
               "v3_temp_dirs": []}
    hc_mod._cleanup_synthetic_rnd(rnd_env, hc_mod.Report())
    assert rnd.get_project(proj["id"]) is None
    assert not any(n.startswith(hc_mod.SYNTHETIC_RND_NAME)
                   for n in _names(rnd))
