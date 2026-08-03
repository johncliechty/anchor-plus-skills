"""Regression: the project-window page MUST carry the responsive viewport meta.

Without `<meta name="viewport" content="width=device-width, ...">` a laptop/PWA
browser falls back to a ~980px layout viewport, scales the page up, and trips the
`.pgrid.layoutd` `max-width:980px` breakpoint — collapsing the right column
(Gandalf / Grass / Deliverables) into a full-width stack. The home page always had
the meta; the project window was missing it (fixed). This pins it.
"""
import importlib


def test_project_window_has_viewport_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import anchor_gui
    importlib.reload(anchor_gui)

    folder = tmp_path / "Proj"
    folder.mkdir(parents=True, exist_ok=True)
    pid = rnd_registry.add_project("Proj", str(folder))["id"]
    html = anchor_gui.render_project_window_html(pid)

    # The meta must be present in the <head> with width=device-width.
    assert "name='viewport'" in html or 'name="viewport"' in html, \
        "project window is missing the viewport meta (right column will collapse on laptops)"
    assert "width=device-width" in html
    head = html.split("</head>", 1)[0]
    assert "width=device-width" in head, "viewport meta must be in the <head>"
