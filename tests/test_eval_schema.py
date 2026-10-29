from delivery.customer_service import Advice
from delivery.eval_checks import checked_judge, code_checks


def test_invalid_schema_never_reaches_judge():
    result = checked_judge('{"category":"delete","reply":"OK"}', Advice,
                           lambda _: (_ for _ in ()).throw(AssertionError("Paid judge called")))
    assert result["code_failures"] == [{"category": "schema", "field": "response"}]
    assert result["judgment"] is None


def test_tool_argument_scope_is_rejected():
    assert code_checks(calls=[{"name": "read_order", "args": {"order": "other"}}],
                       allowed_tools=["read_order"])[0]["category"] == "schema"
