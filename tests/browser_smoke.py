"""Run after building the UI into the package and starting the fixture preview:

    npm --prefix web ci && npm --prefix web run build && cp -r web/dist/. src/openings_research/web/
    uvicorn preview_app:app --app-dir tests --port 18080
"""

import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge" if sys.platform == "win32" else None, headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:18080")
    tree = page.get_by_label("Move tree")
    tree.get_by_text("Start", exact=True).wait_for()
    tree.get_by_text("e4", exact=True).wait_for()  # the book move from the start
    # One researched opening passes the start, so its claims show, with evidence on demand.
    page.get_by_text("White develops the bishop to c4.", exact=False).click()
    page.locator("q").first.wait_for()
    # Walk the line with the keyboard: the header follows and names the opening.
    page.locator("body").click(position={"x": 5, "y": 5})
    for _ in range(5):
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(250)
    nav = page.get_by_label("Current line")
    expect(nav).to_contain_text("Bc4")
    expect(nav).to_contain_text("Italian Game")
    Path(".cache").mkdir(exist_ok=True)
    page.screenshot(path=".cache/explorer-desktop.png")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "horizontal overflow on mobile"
    page.screenshot(path=".cache/explorer-mobile.png", full_page=True)
    assert not errors, errors
    browser.close()
    print("Browser smoke passed: tree, claims and evidence, keyboard walk, opening name, mobile width, no JS errors")
