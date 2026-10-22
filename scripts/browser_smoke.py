"""Run with Playwright installed against a running or completed demo."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8010")
parser.add_argument("--channel", default="chrome")
args = parser.parse_args()
Path("artifacts").mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel=args.channel or None, headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(args.url, wait_until="networkidle")
    page.wait_for_selector("#connection.online")
    assert "9,391" in page.locator("#graph-info").inner_text()
    page.locator("[data-courier]").first.click()
    page.wait_for_function(
        "document.querySelector('#tab-decisions').getAttribute('aria-selected') === 'true'"
    )
    page.locator("#order-filter").select_option("all")
    page.locator("[data-order]").first.wait_for()
    page.locator("[data-order]").first.click()
    page.locator("#decisions .decision").first.wait_for()
    page.locator("#decisions summary").first.click()
    page.screenshot(path="artifacts/ui-desktop.png", full_page=True)
    page.get_by_role("tab", name="Service").click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path="artifacts/ui-mobile.png", full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert not errors, errors
    print(
        json.dumps(
            {
                "browser_errors": errors,
                "desktop": "1440x1100",
                "mobile": "390x844",
                "order_trace": "passed",
                "responsive": "passed",
            }
        )
    )
    browser.close()
