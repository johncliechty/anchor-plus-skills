"""Serve the pre-repair script only inside the existing guarded browser tests."""
import subprocess
from urllib.parse import urlsplit

import pytest


@pytest.fixture(autouse=True)
def original_cave_script(monkeypatch):
    from tests.test_app_header_attention import ReadOnlyUI
    source = subprocess.run(
        ["git", "show", "HEAD:static/high-seat-page.js"], capture_output=True,
        check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    original = ReadOnlyUI.route

    def route(self, request_route):
        if urlsplit(request_route.request.url).path == "/static/high-seat-page.js":
            return request_route.fulfill(body=source, content_type="text/javascript")
        return original(self, request_route)

    monkeypatch.setattr(ReadOnlyUI, "route", route)
