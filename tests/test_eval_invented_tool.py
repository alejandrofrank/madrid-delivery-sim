from delivery.eval_checks import code_checks


def test_cost_mode_finish_is_not_aliased():
    failures = code_checks(calls=[{"name": "finish_finish_decision", "args": {"summary": "x"}}],
                           allowed_tools=["finish_decision"])
    assert failures == [{"category": "invented_tool", "step": 0, "tool": "finish_finish_decision"}]


def test_customer_has_no_tools():
    assert code_checks(calls=[{"name": "finish_decision", "args": {"summary": "x"}}],
                       allowed_tools=[])[0]["category"] == "invented_tool"
