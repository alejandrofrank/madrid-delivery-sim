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
    response = page.request.post(
        args.url.rstrip("/") + "/api/lab/delivery-runs", data={"seed": 42, "playback_seconds": 2}
    )
    assert response.ok
    run = response.json()["id"]
    page.goto(args.url.rstrip("/") + "/delivery-lab?run=" + run, wait_until="networkidle")
    page.wait_for_function(
        "window.deliverySnapshot && window.deliverySnapshot.run.status === 'complete'",
        timeout=60000,
    )
    snapshot = page.evaluate("window.deliverySnapshot")
    assert all(e["state"] == "done" for e in snapshot["events"])
    evidence = page.request.get(args.url + page.locator("#download").get_attribute("href"))
    assert evidence.ok
    assert evidence.json()["checkpoints"]
    assert len(snapshot["city"]["nodes"]) == 1024
    assert len(snapshot["city"]["edges"]) == 3968
    assert len(snapshot["city"]["stores"]) == 12
    assert any("pharmac" in json.dumps(store).lower() for store in snapshot["city"]["stores"])
    delivered = [job for job in snapshot["jobs"] if job["status"] == "delivered"]
    assert len(delivered) >= 2
    assert len({job["courier"] for job in delivered}) >= 2
    assert all(len(job["route"]) > 1 for job in delivered)
    assert any("drop" in incident["kind"] for incident in snapshot["incidents"])
    assert any("traffic" in incident["kind"] for incident in snapshot["incidents"])
    verdicts = {review["verdict"] for review in snapshot["reviews"]}
    assert verdicts & {"approved", "approve"}, verdicts
    assert verdicts & {"denied", "deny", "rejected"}, verdicts
    retry_briefs = [brief for brief in snapshot["briefs"] if brief["attempt"] >= 2]
    assert retry_briefs
    retry_text = json.dumps(retry_briefs[0]["body"]).lower()
    assert "custody" in retry_text and "checkpoint" in retry_text
    assert "source" in retry_text and "event" in retry_text
    assert all(snapshot["invariants"].values()), snapshot["invariants"]
    assert page.locator("#city").get_attribute("data-node-count") == "1024"
    assert page.locator("[data-courier]").count() > 0
    assert page.locator("#error").is_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("button", name="Judge", exact=True).click()
    page.wait_for_function(
        "window.selectedAgentEvidence && "
        "window.selectedAgentEvidence.agent.agent_id === 'judge:fleet'"
    )
    page.screenshot(path="artifacts/flow-desktop.png", full_page=True)
    page.screenshot(path="artifacts/flow-viewport.png")
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
                "delivered": len(delivered),
                "nodes": 1024,
                "roads": 3968,
                "role_boundaries": "passed",
                "responsive": "passed",
                "browser_errors": errors,
            }
        )
    )
    browser.close()
