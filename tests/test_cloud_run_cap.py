from decimal import Decimal

import pytest

from scripts.cloud_run_cap import cap_payload, matches


def test_cap_has_native_enforcement_exact_scope_and_required_notifications():
    body = cap_payload("madrid-delivery-sim-test", Decimal("3"), "EUR")
    assert body["spendCap"] == {"inputState": "CONFIGURED"}
    assert body["budgetFilter"]["services"] == ["services/152E-C115-5142"]
    assert body["thresholdRules"] == [{"thresholdPercent": n} for n in [0.5, 0.8, 1.0]]
    assert body["notificationsRule"] == {"enableProjectLevelRecipients": True}
    body["budgetFilter"]["projects"] = ["projects/123"]
    body["spendCap"] = {"outputState": "CONFIGURED"}
    assert matches(body, "123", Decimal("3"), "EUR")
    for state in ["ENFORCED", "AWAITING_NEXT_PERIOD", "UNSPECIFIED"]:
        body["spendCap"] = {"outputState": state}
        assert not matches(body, "123", Decimal("3"), "EUR")


@pytest.mark.parametrize("project,amount", [("shared-project", "3"),
                                           ("madrid-delivery-sim-test", "20"),
                                           ("madrid-delivery-sim-test", "0")])
def test_cap_rejects_shared_project_or_over_budget(project, amount):
    with pytest.raises(ValueError):
        cap_payload(project, Decimal(amount), "EUR")


def test_cap_verification_rejects_wrong_currency_amount_service_and_project():
    body = cap_payload("madrid-delivery-sim-test", Decimal("3"), "EUR")
    body["budgetFilter"]["projects"] = ["projects/123"]
    body["spendCap"] = {"outputState": "CONFIGURED"}
    assert not matches(body, "456", Decimal("3"), "EUR")
    assert not matches(body, "123", Decimal("4"), "EUR")
    assert not matches(body, "123", Decimal("3"), "USD")
    body["budgetFilter"]["calendarPeriod"] = "YEAR"
    assert not matches(body, "123", Decimal("3"), "EUR")
    body["budgetFilter"]["calendarPeriod"] = "MONTH"
    body["budgetFilter"]["creditTypesTreatment"] = "INCLUDE_ALL_CREDITS"
    assert not matches(body, "123", Decimal("3"), "EUR")
    body["budgetFilter"]["creditTypesTreatment"] = "EXCLUDE_ALL_CREDITS"
    body["budgetFilter"]["services"] = ["services/other"]
    assert not matches(body, "123", Decimal("3"), "EUR")
