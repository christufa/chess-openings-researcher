"""Run after starting uvicorn preview_app:app --app-dir tests --port 18080."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge" if sys.platform == "win32" else None, headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:18080")
    page.get_by_text("White develops the bishop to c4.", exact=True).wait_for()
    page.get_by_text("Inspect source evidence", exact=True).click()
    page.locator("blockquote").wait_for()
    page.get_by_role("button", name="Opening lines", exact=True).click()
    page.get_by_text("e4 e5 Nf3 Nc6 Bc4", exact=True).wait_for()
    page.get_by_role("button", name="Research gaps", exact=True).click()
    page.get_by_text("Suggested search:", exact=False).first.wait_for()
    page.get_by_role("button", name="Compare with selected run").click()
    page.wait_for_function("document.querySelector('#diff').textContent.includes('retained')")
    Path(".databricks").mkdir(exist_ok=True)
    page.screenshot(path=".databricks/explorer-desktop.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=".databricks/explorer-mobile.png", full_page=True)
    assert not errors, errors
    browser.close()
    print("Browser smoke passed: evidence, lines, gaps, comparison, mobile overflow, no JS errors")
