"""Explicit live-cloud opt-in: exercise the UI switch and a seeded recovery."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--live-cloud", action="store_true", required=True)
parser.add_argument("--url", default="http://127.0.0.1:8010")
args = parser.parse_args()
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(args.url + "/delivery-lab", wait_until="networkidle")
    page.wait_for_selector('#city[data-node-count="1024"]')
    page.get_by_role("button", name="Configure", exact=True).click()
    assert not page.locator('#agent-mode option[value="gcp_ai"]').is_disabled()
    for key, value in {
        "seed": "71",
        "duration_minutes": "15",
        "orders_per_hour": "4",
        "traffic_multiplier": "1",
        "dropout_rate": "0.4",
    }.items():
        page.locator(f'[name="{key}"]').fill(value)
    page.locator("#agent-mode").select_option("gcp_ai")
    page.get_by_role("button", name="Save next-run settings", exact=True).click()
    for index in range(1, 13):
        page.locator(f'[data-store="store-{index}"] rect').click()
        page.locator('[name="couriers"]').fill("3" if index == 1 else "0")
        page.locator('[name="demand_weight"]').fill("1" if index == 1 else "0")
        page.get_by_role("button", name="Save shop for next run", exact=True).click()
    page.locator("#speed").select_option("2")
    page.get_by_role("button", name="Start simulation", exact=True).click()
    page.wait_for_function(
        "window.deliverySnapshot?.config?.agent_mode==='gcp_ai' && "
        "window.deliverySnapshot.run.status==='complete'",
        timeout=120000,
    )
    cloud = page.evaluate("window.deliverySnapshot")
    assert cloud["agent_runtime"]["model_calls"] >= 1, cloud["agent_runtime"]
    audits = [
        d["detail"]["cloud_judgement"]
        for d in cloud["decisions"]
        if "cloud_judgement" in d["detail"]
    ]
    assert any(a.get("source") == "model" and a.get("fallback") is None for a in audits), audits
    assert all(cloud["invariants"].values())
    page.get_by_role("button", name="Judge", exact=True).click()
    page.wait_for_function("window.selectedAgentEvidence?.agent.agent_id==='judge:fleet'")
    page.screenshot(path="artifacts/gcp-switch-cloud.png", full_page=True)
    page.get_by_role("button", name="Configure", exact=True).click()
    page.locator("#agent-mode").select_option("local")
    page.get_by_role("button", name="Save next-run settings", exact=True).click()
    page.get_by_role("button", name="Start simulation", exact=True).click()
    page.wait_for_function(
        "window.deliverySnapshot?.config?.agent_mode==='local' && "
        "window.deliverySnapshot.run.status==='complete'",
        timeout=120000,
    )
    local = page.evaluate("window.deliverySnapshot")
    assert local["agent_runtime"]["model_calls"] == 0
    assert all(local["invariants"].values())
    assert not any("cloud_judgement" in d["detail"] for d in local["decisions"])
    assert not errors, errors
    receipt = {
        "cloud_run": cloud["run"]["id"],
        "local_run": local["run"]["id"],
        "cloud_runtime": cloud["agent_runtime"],
        "cloud_audits": audits,
        "local_model_calls": 0,
        "invariants": cloud["invariants"],
        "browser_errors": errors,
    }
    Path("artifacts/gcp-switch-verification.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))
    browser.close()
