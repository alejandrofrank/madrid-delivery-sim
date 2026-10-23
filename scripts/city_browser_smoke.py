"""Exercise map-first city configuration, scheduled orders and scoped memory."""

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
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(args.url.rstrip("/") + "/delivery-lab", wait_until="networkidle")
    page.wait_for_selector('#city[data-node-count="1024"]')
    assert page.locator("[data-store]").count() == 12
    page.get_by_role("button", name="Configure", exact=True).click()
    page.locator('[name="duration_minutes"]').fill("15")
    page.locator('[name="orders_per_hour"]').fill("12")
    page.get_by_role("button", name="Save next-run settings").click()
    page.locator("#speed").select_option("2")
    for index in range(1, 4):
        page.locator(f'[data-store="store-{index}"]').click()
        page.locator('[name="couriers"]').fill("1")
        page.locator('[name="enabled"]').check()
        page.get_by_role("button", name="Save shop for next run").click()
    page.get_by_role("button", name="Start simulation").click()
    page.wait_for_function(
        "window.deliverySnapshot && "
        "['complete','completed','finished'].includes(window.deliverySnapshot.run.status)",
        timeout=60000,
    )
    snapshot = page.evaluate("window.deliverySnapshot")
    assert len(snapshot["city"]["nodes"]) == 1024
    assert len(snapshot["city"]["edges"]) == 3968
    schedule = snapshot["order_schedule"]
    assert schedule
    assert any(order["arrival_sim"] > 0 for order in schedule)
    assert len({order["arrival_sim"] for order in schedule}) > 1
    page.locator('[data-store="store-1"]').click()
    page.get_by_role("button", name="Team", exact=True).click()
    page.locator('[data-agent="inventory:store-1"]').click()
    page.wait_for_function("window.selectedAgentEvidence")
    evidence = page.evaluate("window.selectedAgentEvidence")
    assert evidence["agent"]["agent_id"] == "inventory:store-1"
    assert isinstance(evidence["memory"], list)
    assert "Private memory" in page.locator("#agent-content").inner_text()
    assert page.locator("#city").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path="artifacts/city-desktop.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("#city").is_visible()
    page.screenshot(path="artifacts/city-mobile.png", full_page=True)
    page.reload(wait_until="networkidle")
    page.wait_for_function("window.deliverySnapshot")
    assert page.evaluate("window.deliverySnapshot.run.id") == snapshot["run"]["id"]
    assert not errors, errors
    print(json.dumps({"run": snapshot["run"]["id"], "orders": len(schedule), "errors": errors}))
    browser.close()
