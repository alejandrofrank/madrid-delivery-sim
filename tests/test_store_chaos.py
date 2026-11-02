import json

import pytest

from delivery.chaos import ChaosConfig, schedule
from delivery.store_conditions import STORE_KINDS
from delivery.store_evals import MANIFEST, passed, run_case, validate


def test_seeded_store_disruptions_leave_city_seed_sequence_unchanged():
    old = schedule(ChaosConfig(random_events=3), 42, 1800)
    new = schedule(ChaosConfig(random_events=3, random_store_events=4), 42, 1800)
    assert [e for e in new if e.kind not in STORE_KINDS] == old
    assert new == schedule(ChaosConfig(random_events=3, random_store_events=4), 42, 1800)
    assert len(new) == 7


def test_store_gate_rejects_missing_or_forged_evidence():
    assert not validate({})
    assert not validate({"kind": "store-evals", "fixture_hash": "invented", "rows": []})


@pytest.mark.integration
@pytest.mark.parametrize("kind", STORE_KINDS)
def test_store_disruptions_recover_over_a2a(db_url, kind):
    from delivery.simulation import initialize

    initialize(db_url)
    result = run_case(kind, 42, db_url)
    assert passed(kind, result, json.loads(MANIFEST.read_text())["criteria"]), result
