"""Exercise the real local lab, including checkpoint evidence and mobile layout."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8010")
parser.add_argument("--channel", default="chrome")
parser.add_argument(
    "--sample-date", help="Exercise an installed local history date instead of fixture"
)
args = parser.parse_args()
Path("artifacts").mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel=args.channel or None, headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(args.url + "/lab", wait_until="domcontentloaded")
    if args.sample_date:
        page.wait_for_function(
            "date => [...document.getElementById('catalogue').options]"
            ".some(option => option.value === 'history:' + date)",
            arg=args.sample_date,
        )
        page.locator("#catalogue").select_option("history:" + args.sample_date)
    else:
        page.locator("#catalogue").select_option("fixture")
    page.get_by_role("button", name="Run last-unit scenario").click()
    page.wait_for_function(
        "document.getElementById('status').textContent === 'COMPLETE'", timeout=60000
    )
    page.wait_for_function("document.getElementById('checkpoint').options.length === 7")
    assert page.locator("#available").inner_text() == "6"
    assert page.locator("#invariants").inner_text() == "PASS"
    assert page.locator("#error").is_hidden()
    assert page.locator("#store option").count() == 5
    assert page.locator("#stock tr").count() > 0
    assert "inventory:store-1" in page.locator("#agent-scope").inner_text()
    assert "model budget $0" in page.locator("#agent-budget").inner_text()
    if args.sample_date:
        assert args.sample_date in page.locator("#provenance").inner_text()
        history = page.request.get(args.url + "/api/lab/history").json()
        for day in history["days"]:
            if day["status"] == "missing":
                assert day["date"] in page.locator("#history-coverage").inner_text()
                option = page.locator(f"#catalogue option[value='history:{day['date']}']")
                assert option.evaluate("element => element.disabled") is True
    page.locator("#checkpoint").select_option("0")
    assert page.locator("#reserved").inner_text() == "0"
    assert "leased" in page.locator("#events").inner_text()
    page.locator("#checkpoint").select_option("1")
    assert page.locator("#available").inner_text() == "0"
    assert "reserved" in page.locator("#baskets").inner_text()
    assert "rejected" in page.locator("#baskets").inner_text()
    page.locator("#checkpoint").select_option("3")
    assert "minute 15" in page.locator("#eta").inner_text()
    page.get_by_role("button", name="Inspect South Market").click()
    assert page.locator("#store").input_value() == "store-3"
    assert "inventory:store-3" in page.locator("#agent-scope").inner_text()
    page.locator("#store").select_option("store-1")
    prefix = "lab-history" if args.sample_date else "lab"
    page.screenshot(path=f"artifacts/{prefix}-desktop.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=f"artifacts/{prefix}-mobile.png", full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.locator("#checkpoint").select_option("live")
    assert page.locator("#available").inner_text() == "6"
    assert not errors, errors
    print(
        json.dumps(
            {
                "errors": errors,
                "crash_checkpoint": "passed",
                "last_unit": "passed",
                "delayed_supply": "passed",
                "store_selection": "passed",
                "mobile_overflow": False,
            }
        )
    )
    browser.close()
