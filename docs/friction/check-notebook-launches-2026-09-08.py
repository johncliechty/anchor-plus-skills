"""Read-only browser evidence for the existing classroom notebook launch pages."""
import json
import winreg
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Services\anchor\Parameters") as key:
        entries = winreg.QueryValueEx(key, "AppEnvironmentExtra")[0]
    token = next(entry.partition("=")[2] for entry in entries
                 if entry.startswith("ANCHOR_TOKEN="))
    output = Path(__file__).parent
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1024, "height": 1366},
                                      is_mobile=True, has_touch=True)

        def authorize_anchor(route):
            if route.request.method != "GET":
                route.abort()
                return
            headers = dict(route.request.headers)
            headers["Authorization"] = "Bearer " + token
            route.continue_(headers=headers)

        context.route("http://127.0.0.1:8777/**", authorize_anchor)
        for language in ("python", "R"):
            page = context.new_page()
            target = ("http://127.0.0.1:8777/artifact/2934ea6de8f64aca90c716d568298d75"
                      "?path=Student%20Summaries/weeks/week-02/notebooks/"
                      f"RUN-week02-{language}.html")
            entry = {"language": language, "executed_cells": False}
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_function(
                    "() => document.title.includes('JupyterLab')", timeout=25000)
                page.wait_for_selector(".jp-NotebookPanel", state="attached", timeout=25000)
                expected = f"week02-{language}.ipynb"
                page.wait_for_function(
                    "name => Array.from(document.querySelectorAll("
                    "'.lm-TabBar-tab.lm-mod-current .lm-TabBar-tabLabel'))"
                    ".some(el => el.textContent.trim() === name)",
                    arg=expected, timeout=25000)
                title = page.title()
                entry.update(title=title,
                             notebook_panels=page.locator(".jp-NotebookPanel").count(),
                             cells=page.locator(".jp-Notebook .jp-Cell").count(),
                             tab_labels=page.locator(".lm-TabBar-tabLabel").all_text_contents())
                page.screenshot(path=str(output / f"2026-09-08-week02-{language}.png"))
            except Exception as error:
                # URLs may contain auth material; record only exception class and UI title.
                entry.update(error_type=type(error).__name__, title=page.title(),
                             tab_labels=page.locator(".lm-TabBar-tabLabel").all_text_contents())
            results.append(entry)
            page.close()
        browser.close()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
