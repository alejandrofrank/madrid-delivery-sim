"""Verify the local synthetic basket-to-delivery inspector against a running server."""

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
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(args.url.rstrip("/") + "/delivery-lab", wait_until="networkidle")
    page.locator("#duration").fill("2")
    page.get_by_role("button", name="Run basket delivery").click()
    page.wait_for_function(
        "window.deliverySnapshot && window.deliverySnapshot.run.status === 'complete' && "
        "window.deliverySnapshot.jobs.length > 0 && "
        "window.deliverySnapshot.jobs.every(j => j.status === 'delivered')",
        timeout=60000,
    )
    snapshot = page.evaluate("window.deliverySnapshot")
    assert all(e["state"] == "done" for e in snapshot["events"])
    evidence = page.request.get(args.url + page.locator("#download").get_attribute("href"))
    assert evidence.ok
    assert evidence.json()["checkpoints"]
    assert len(snapshot["city"]["nodes"]) == 100
    assert len(snapshot["city"]["edges"]) == 360
    assert all(len(j["route"]) > 1 for j in snapshot["jobs"])
    assert all(snapshot["invariants"].values()), snapshot["invariants"]
    assert page.locator("[data-node]").count() == 100
    assert page.locator("[data-road]").count() == 360
    assert page.locator("[data-role]").count() == 3
    assert page.locator("[data-courier]").count() > 0
    assert page.locator("#error").is_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#decisions summary").first.click()
    page.locator("#events summary").first.click()
    page.screenshot(path="artifacts/flow-desktop.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path="artifacts/flow-mobile.png", full_page=True)
    page.reload(wait_until="networkidle")
    page.wait_for_function(
        "window.deliverySnapshot && window.deliverySnapshot.run.status === 'complete'"
    )
    assert not errors, errors
    print(
        json.dumps(
            {
                "run": snapshot["run"]["id"],
                "delivered": len(snapshot["jobs"]),
                "nodes": 100,
                "roads": 360,
                "role_boundaries": "passed",
                "responsive": "passed",
                "browser_errors": errors,
            }
        )
    )
    browser.close()
