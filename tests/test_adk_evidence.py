from delivery.adk_contracts import VertexProfile
from delivery.adk_evidence import usage_cost


def profile(**changes):
    return VertexProfile(
        project="bakiano-test-only",
        location="global",
        model="gemini-3.5-flash-lite",
        input_usd_per_million=0.30,
        output_usd_per_million=2.50,
        **changes,
    )


def test_cost_uses_reported_output_thinking_and_cached_tokens():
    usage = {
        "known": True,
        "prompt_token_count": 1000,
        "candidates_token_count": 100,
        "thoughts_token_count": 50,
        "cached_content_token_count": 500,
    }
    assert usage_cost(usage, profile(cached_input_usd_per_million=0.03)) == "0.00054000"
    assert usage_cost(usage, profile()) is None


def test_missing_or_invalid_usage_never_becomes_zero_cost():
    for usage in (
        None,
        {},
        {"known": False},
        {"known": True},
        {"known": True, "prompt_token_count": -1},
        {"known": True, "prompt_token_count": True},
        {"known": True, "prompt_token_count": 10, "cached_content_token_count": 20},
    ):
        assert usage_cost(usage, profile()) is None
