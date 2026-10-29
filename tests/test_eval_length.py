import pytest

from delivery.customer_service import Advice
from delivery.eval_checks import checked_judge, code_checks


@pytest.mark.parametrize("length,failed", [(0, True), (500, False), (501, True)])
def test_summary_character_boundary(length, failed):
    result = code_checks(calls=[{"name": "finish_decision", "args": {"summary": "é" * length}}],
                         allowed_tools=["finish_decision"])
    assert bool(result) is failed
    assert all(r["category"] == "length" for r in result)


def test_reply_length_stops_semantic_judgment():
    result = checked_judge({"category": "status", "reply": "x" * 501}, Advice,
                           lambda _: pytest.fail("Must not judge invalid reply"))
    assert result["code_failures"][0]["category"] == "length"
