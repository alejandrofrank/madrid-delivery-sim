"""Create or verify a native Cloud Run cap before opening an ephemeral demo.

The pinned Terraform provider does not expose spendCap yet. This operator-only
step uses the documented Billing Budgets API, not a delayed Pub/Sub kill switch.
It never lifts an enforced cap or edits a budget for another project/service.
"""

import argparse
import json
import subprocess
import urllib.request
from decimal import Decimal
from typing import Any
from urllib.parse import quote

SERVICE = "services/152E-C115-5142"


def cap_payload(project: str, amount: Decimal, currency: str) -> dict[str, Any]:
    if not project.startswith("madrid-delivery-sim-") or not 0 < amount <= 4:
        raise ValueError("Expected dedicated Madrid project and cap between zero and four")
    if currency not in {"EUR", "USD"}:
        raise ValueError("Use the billing account currency")
    units = int(amount)
    return {
        "displayName": f"{project} Cloud Run automatic stop",
        "budgetFilter": {"projects": [f"projects/{project}"], "services": [SERVICE],
                         "creditTypesTreatment": "EXCLUDE_ALL_CREDITS",
                         "calendarPeriod": "MONTH"},
        "amount": {"specifiedAmount": {"currencyCode": currency, "units": str(units),
                                       "nanos": int((amount - units) * 10**9)}},
        "thresholdRules": [{"thresholdPercent": n} for n in (0.5, 0.8, 1.0)],
        "notificationsRule": {"enableProjectLevelRecipients": True},
        "spendCap": {"inputState": "CONFIGURED"},
    }


def matches(budget: dict[str, Any], project_number: str, amount: Decimal,
            currency: str) -> bool:
    filters = budget.get("budgetFilter", {})
    money = budget.get("amount", {}).get("specifiedAmount", {})
    actual = Decimal(money.get("units", "0")) + Decimal(money.get("nanos", 0)) / 10**9
    return bool(
        filters.get("projects") == [f"projects/{project_number}"]
        and filters.get("services") == [SERVICE]
        and filters.get("calendarPeriod") == "MONTH"
        and filters.get("creditTypesTreatment") == "EXCLUDE_ALL_CREDITS"
        and budget.get("spendCap", {}).get("outputState") == "CONFIGURED"
        and actual == amount and money.get("currencyCode") == currency
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--billing-account", required=True)
    parser.add_argument("--amount", type=Decimal, default=Decimal("3"))
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    payload = cap_payload(args.project, args.amount, args.currency)
    number = subprocess.check_output([
        "gcloud", "projects", "describe", args.project, "--format=value(projectNumber)"
    ], text=True).strip()
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    root = f"https://billingbudgets.googleapis.com/v1/billingAccounts/{args.billing_account}/budgets"

    def request(url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": f"Bearer {token}",
                                              "x-goog-user-project": args.project,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            return dict(json.load(response))

    budgets: list[dict[str, Any]] = []
    scoped = root + "?scope=" + quote(f"projects/{args.project}", safe="")
    url = scoped
    while True:
        page = request(url)
        budgets.extend(page.get("budgets", []))
        if not page.get("nextPageToken"):
            break
        url = scoped + "&pageToken=" + quote(page["nextPageToken"], safe="")
    existing = [b for b in budgets if b.get("displayName") == payload["displayName"]]
    if len(existing) > 1:
        raise RuntimeError("Ambiguous cap budgets: inspect in Billing console")
    if existing:
        receipt = existing[0]
    elif args.verify_only:
        raise RuntimeError("No cap configured: deployment is blocked")
    else:
        receipt = request(root, payload)
    if not matches(receipt, number, args.amount, args.currency):
        raise RuntimeError("Cap is not configured with the required scope/amount; do not deploy")
    print(json.dumps({"name": receipt["name"], "project": args.project,
                      "currency": args.currency, "amount": str(args.amount),
                      "state": "CONFIGURED", "service": "Cloud Run"}))


if __name__ == "__main__":
    main()
