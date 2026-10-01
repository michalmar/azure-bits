from __future__ import annotations

from app.pricing import calculate_cost


def test_calculate_cost_separates_token_categories() -> None:
    usage = {
        "input_tokens": 1_000,
        "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 100},
        "output_tokens": 300,
    }
    prices = {"input": 4.0, "cachedInput": 0.4, "cacheWrite": 5.0, "output": 20.0}

    result = calculate_cost(usage, prices)

    assert result["billableTokens"] == {
        "input": 700,
        "cachedInput": 200,
        "cacheWrite": 100,
        "output": 300,
    }
    assert result["amount"] == 0.00938
