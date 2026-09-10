"""Hermetic browser canaries for the actual shipped notebook action renderer.

All page requests are intercepted. No Anchor/Jupyter service, real credentials,
projects, model calls, downloads, or notebook execution are involved.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urljoin, urlsplit

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect

ORIGIN = "http://anchor.test"
PROJECT_ID = "synthetic-notebook-project"
TOKEN = "placeholder"
DIRECTORY = "lessons/unit 2"
SOURCE = "lesson.py"
SCRIPT = Path(__file__).resolve().parents[1] / "steward_cockpit" / "static" / "notebook-actions.js"


def source_item(status="unconverted", notebook=None):
    return {
        "what": "Lesson",
        "step": "2",
        "path": SOURCE,
        "notebook_product": {
            "source": SOURCE,
            "notebook": notebook,
            "status": status,
            "can_convert": status == "unconverted",
            "can_open": notebook is not None,
        },
    }


def successful_response(notebook="lesson.ipynb"):
    return {
        "ok": True,
        "notebook_product": {
            "source": SOURCE,
            "notebook": notebook,
            "status": "current",
            "can_convert": False,
            "can_open": True,
            "message": "Synthetic notebook ready on the Anchor host.",
        },
    }


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as playwright:
        owned_browser = playwright.chromium.launch(headless=True)
        try:
            yield owned_browser
        finally:
            owned_browser.close()


@pytest.fixture
def ui(browser):
    context = browser.new_context(service_workers="block")
    page = context.new_page()
    page.set_default_timeout(5000)
    state = SimpleNamespace(
        page=page,
        context=context,
        requests=[],
        unexpected_requests=[],
        popups=[],
        response_status=200,
        response_body=successful_response(),
    )

    def intercept(route):
        request = route.request
        record = {
            "url": request.url,
            "method": request.method,
            "headers": dict(request.all_headers()),
            "post_data": request.post_data,
        }
        state.requests.append(record)
        parsed = urlsplit(request.url)
        if parsed.scheme != "http" or parsed.netloc != "anchor.test":
            state.unexpected_requests.append(record)
            route.abort()
        elif parsed.path == "/" and request.method == "GET":
            route.fulfill(status=200, content_type="text/html", body=(
                "<!doctype html><html><head><meta charset='utf-8'></head>"
                "<body><div id='mount'></div></body></html>"
            ))
        elif parsed.path == "/api/steward/notebook-register" and request.method == "POST":
            route.fulfill(status=state.response_status, content_type="application/json",
                          body=json.dumps(state.response_body))
        elif parsed.path == "/favicon.ico" and request.method == "GET":
            route.fulfill(status=204, body="")
        else:
            # Opening/downloading/executing is intentionally never performed by
            # these tests. An unexpected attempt is recorded and blocked.
            state.unexpected_requests.append(record)
            route.abort()

    # Context interception also protects a popup's initial request; the page
    # route owns the normal renderer requests and has routing precedence.
    context.route("**/*", intercept)
    page.route("**/*", intercept)
    page.on("popup", lambda popup: state.popups.append(popup))
    page.add_init_script(
        "window.STEWARD_PID = " + json.dumps(PROJECT_ID) + ";\n"
        "window.STEWARD_TOKEN = " + json.dumps(TOKEN) + ";\n"
        "window.__notebookRefreshEvents = 0;\n"
        "window.__windowOpenAttempts = [];\n"
        "window.addEventListener('anchor-notebooks-changed', function () {"
        "  window.__notebookRefreshEvents += 1;"
        "});\n"
        "window.open = function () {"
        "  window.__windowOpenAttempts.push(Array.from(arguments)); return null;"
        "};\n"
    )
    try:
        page.goto(ORIGIN + "/")
        page.add_script_tag(content=SCRIPT.read_text(encoding="utf-8"))
        yield state
    finally:
        context.close()


def render(ui, item):
    ui.page.evaluate(
        "({item, dir}) => {"
        " const product = window.AnchorNotebooks.render(item, dir);"
        " document.getElementById('mount').replaceChildren(product);"
        "}",
        {"item": item, "dir": DIRECTORY},
    )


def registration_requests(ui):
    return [request for request in ui.requests
            if urlsplit(request["url"]).path == "/api/steward/notebook-register"]


def assert_registration(request, *, regenerate):
    parsed = urlsplit(request["url"])
    assert parsed.scheme == "http" and parsed.netloc == "anchor.test"
    assert parsed.path == "/api/steward/notebook-register"
    assert parse_qs(parsed.query) == {"pid": [PROJECT_ID]}
    assert request["method"] == "POST"
    assert request["headers"].get("authorization") == "Bearer " + TOKEN
    assert json.loads(request["post_data"]) == {
        "dir": DIRECTORY,
        "source": SOURCE,
        "what": "Lesson",
        "step": "2",
        "regenerate": regenerate,
    }


def assert_safe_open_link(ui):
    link = ui.page.get_by_role("link", name="Open notebook", exact=False)
    expect(link).to_be_visible()
    target = urlsplit(urljoin(ORIGIN + "/", link.get_attribute("href")))
    assert target.scheme == "http" and target.netloc == "anchor.test"
    assert target.path == "/api/steward/notebook-open"
    assert parse_qs(target.query) == {
        "pid": [PROJECT_ID], "dir": [DIRECTORY], "path": [SOURCE], "token": [TOKEN],
    }
    assert link.get_attribute("target") == "_blank"
    assert {"noopener", "noreferrer"}.issubset(set((link.get_attribute("rel") or "").split()))


def assert_source_download_stays_on_anchor(ui):
    link = ui.page.get_by_role("link", name="Source", exact=True)
    expect(link).to_be_visible()
    target = urlsplit(urljoin(ORIGIN + "/", link.get_attribute("href")))
    assert target.scheme == "http" and target.netloc == "anchor.test"
    assert target.path.startswith("/api/steward/")
    query = parse_qs(target.query)
    assert query.get("download") == ["1"]
    assert any(SOURCE in value for values in query.values() for value in values)


def assert_no_automatic_open_or_execution(ui):
    assert ui.unexpected_requests == []
    assert all(urlsplit(request["url"]).netloc == "anchor.test" for request in ui.requests)
    assert ui.page.evaluate("window.__windowOpenAttempts") == []
    assert ui.popups == []
    assert len(ui.context.pages) == 1
    api_paths = [urlsplit(request["url"]).path for request in ui.requests
                 if urlsplit(request["url"]).path.startswith("/api/")]
    assert all(path == "/api/steward/notebook-register" for path in api_paths)


def test_render_is_passive_and_conversion_updates_links_and_dispatches_refresh(ui):
    render(ui, source_item())
    create = ui.page.get_by_role("button", name="Create notebook", exact=True)
    expect(create).to_be_visible()
    assert_source_download_stays_on_anchor(ui)
    expect(ui.page.get_by_role("link", name="Open notebook", exact=False)).to_have_count(0)
    assert registration_requests(ui) == []
    assert ui.page.evaluate("window.__notebookRefreshEvents") == 0
    assert_no_automatic_open_or_execution(ui)

    create.click()
    assert_safe_open_link(ui)
    assert_source_download_stays_on_anchor(ui)
    expect(ui.page.get_by_role("button", name="Create notebook", exact=True)).to_have_count(0)
    requests = registration_requests(ui)
    assert len(requests) == 1
    assert_registration(requests[0], regenerate=False)
    assert ui.page.evaluate("window.__notebookRefreshEvents") == 1
    assert_no_automatic_open_or_execution(ui)


@pytest.mark.parametrize("status", ["source_changed", "notebook_edited"])
def test_new_revision_preserves_source_association_and_requires_explicit_click(ui, status):
    ui.response_body = successful_response("lesson.rev2.ipynb")
    render(ui, source_item(status=status, notebook="lesson.ipynb"))
    revise = ui.page.get_by_role("button", name="New notebook revision", exact=True)
    expect(revise).to_be_visible()
    assert registration_requests(ui) == []
    assert_no_automatic_open_or_execution(ui)

    revise.click()
    assert_safe_open_link(ui)
    assert_source_download_stays_on_anchor(ui)
    expect(ui.page.get_by_role("button", name="New notebook revision", exact=True)).to_have_count(0)
    requests = registration_requests(ui)
    assert len(requests) == 1
    assert_registration(requests[0], regenerate=True)
    assert ui.page.evaluate("window.__notebookRefreshEvents") == 1
    assert_no_automatic_open_or_execution(ui)


@pytest.mark.parametrize("error_field", ["error", "reason"])
def test_conflict_message_is_visible_and_creation_can_be_retried_without_losing_source(ui, error_field):
    ui.response_status = 409
    ui.response_body = {"ok": False, error_field: "Conflict preserved"}
    render(ui, source_item())
    create = ui.page.get_by_role("button", name="Create notebook", exact=True)
    create.click()
    expect(ui.page.get_by_text("Conflict preserved", exact=False)).to_be_visible()
    expect(create).to_be_enabled()
    assert_source_download_stays_on_anchor(ui)
    expect(ui.page.get_by_role("link", name="Open notebook", exact=False)).to_have_count(0)
    assert ui.page.evaluate("window.__notebookRefreshEvents") == 0
    assert len(registration_requests(ui)) == 1
    assert_registration(registration_requests(ui)[0], regenerate=False)
    assert_no_automatic_open_or_execution(ui)

    ui.response_status = 200
    ui.response_body = successful_response()
    create.click()
    assert_safe_open_link(ui)
    assert_source_download_stays_on_anchor(ui)
    assert len(registration_requests(ui)) == 2
    assert_registration(registration_requests(ui)[1], regenerate=False)
    assert ui.page.evaluate("window.__notebookRefreshEvents") == 1
    assert_no_automatic_open_or_execution(ui)
