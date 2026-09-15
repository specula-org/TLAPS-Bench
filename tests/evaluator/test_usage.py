"""Provider-neutral structured usage schema."""

from evaluator.usage import (
    RequestUsage,
    UsageCost,
    UsageSummary,
    aggregate_token_usage,
    format_token_usage,
    result_token_usage,
)


def test_legacy_adapter_preserves_old_totals_and_marks_unknown_buckets():
    usage = UsageSummary.from_legacy(120, 30, source="test_legacy")

    assert (usage.legacy_input_tokens, usage.legacy_output_tokens) == (120, 30)
    assert usage.to_dict() == {
        "schema_version": 1,
        "status": "incomplete",
        "available": True,
        "complete": False,
        "is_lower_bound": False,
        "input_tokens": 120,
        "output_tokens": 30,
        "cache_read_input_tokens": None,
        "cache_write_input_tokens": None,
        "reasoning_output_tokens": None,
        "model_requests": None,
        "model_time_secs": None,
        "costs": [],
        "sources": ["test_legacy"],
        "runtime_versions": [],
        "requests": [],
        "warnings": [],
    }


def test_unavailable_structured_usage_is_not_rendered_as_legacy_zero() -> None:
    result = {
        "input_tokens": 0,
        "output_tokens": 0,
        "usage": UsageSummary(available=False).to_dict(),
    }

    assert format_token_usage(result_token_usage(result)) == "unavailable"
    assert format_token_usage(aggregate_token_usage([result]), verbose=True) == "unavailable"


def test_lower_bound_token_usage_is_labeled() -> None:
    usage = UsageSummary(input_tokens=12, output_tokens=3, available=True, is_lower_bound=True)
    result = {"usage": usage.to_dict()}

    assert format_token_usage(result_token_usage(result)) == "≥12/3"
    assert format_token_usage(aggregate_token_usage([result]), verbose=True) == "at least 12 input / 3 output"


def test_request_totals_do_not_double_count_cache_or_reasoning():
    requests = [
        RequestUsage(
            input_tokens=100,
            output_tokens=40,
            cache_read_input_tokens=60,
            cache_write_input_tokens=10,
            reasoning_output_tokens=25,
            duration_secs=0.5,
        ),
        RequestUsage(
            input_tokens=50,
            output_tokens=20,
            cache_read_input_tokens=20,
            cache_write_input_tokens=0,
            reasoning_output_tokens=5,
            duration_secs=0.25,
        ),
    ]

    usage = UsageSummary.from_requests(requests, source="test", complete=True)

    assert usage.input_tokens == 150
    assert usage.output_tokens == 60
    assert usage.cache_read_input_tokens == 80
    assert usage.cache_write_input_tokens == 10
    assert usage.reasoning_output_tokens == 30
    assert usage.model_time_secs == 0.75


def test_partial_request_fields_are_explicit_lower_bounds():
    usage = UsageSummary.from_requests(
        [
            RequestUsage(input_tokens=100, output_tokens=10, duration_secs=0.2),
            RequestUsage(input_tokens=None, output_tokens=5, duration_secs=None),
        ],
        source="test",
        complete=True,
    )

    assert (usage.input_tokens, usage.output_tokens) == (100, 15)
    assert usage.model_time_secs == 0.2
    assert usage.status == "lower_bound"
    assert "input_tokens is missing for some model requests; total is a lower bound" in usage.warnings
    assert "model_time_secs is missing for some model requests; total is a lower bound" in usage.warnings


def test_core_field_missing_from_every_request_cannot_be_complete():
    usage = UsageSummary.from_requests(
        [RequestUsage(input_tokens=10, output_tokens=None), RequestUsage(input_tokens=20, output_tokens=None)],
        source="test",
        complete=True,
    )

    assert usage.input_tokens == 30
    assert usage.output_tokens is None
    assert usage.status == "lower_bound"
    assert "output_tokens is unavailable for every model request; total is a lower bound" in usage.warnings


def test_exact_empty_request_set_requires_authoritative_zero_totals():
    ambiguous = UsageSummary.from_requests([], source="test", complete=True)
    exact = UsageSummary.from_requests(
        [],
        source="test",
        complete=True,
        totals={"input_tokens": 0, "output_tokens": 0, "model_requests": 0},
    )

    assert ambiguous.status == "incomplete"
    assert ambiguous.input_tokens is None
    assert "exact zero-request summary" in ambiguous.warnings[0]
    assert exact.status == "complete"
    assert (exact.input_tokens, exact.output_tokens, exact.model_requests) == (0, 0, 0)


def test_aggregate_only_request_set_can_be_complete():
    usage = UsageSummary.from_requests(
        [],
        source="test",
        complete=True,
        totals={"input_tokens": 30, "output_tokens": 90, "model_requests": 4},
    )

    assert usage.status == "complete"
    assert (usage.input_tokens, usage.output_tokens, usage.model_requests) == (30, 90, 4)
    assert usage.warnings == ()


def test_authoritative_token_totals_are_not_coerced():
    usage = UsageSummary.from_requests(
        [RequestUsage(input_tokens=10, output_tokens=5)],
        source="test",
        complete=True,
        totals={"input_tokens": 10.5, "output_tokens": True},
    )

    assert (usage.input_tokens, usage.output_tokens) == (10, 5)
    assert usage.status == "incomplete"
    assert "invalid authoritative input_tokens total" in usage.warnings[0]
    assert "invalid authoritative output_tokens total" in usage.warnings[1]


def test_merge_does_not_present_known_plus_unknown_as_an_exact_total():
    known = UsageSummary(
        input_tokens=100,
        output_tokens=10,
        model_requests=1,
        costs=(UsageCost(0.1, "provider_monetary", "provider.cost"),),
        complete=True,
    )
    unknown = UsageSummary(
        input_tokens=None,
        output_tokens=5,
        model_requests=1,
        complete=False,
    )

    merged = known.merge(unknown)

    assert (merged.input_tokens, merged.output_tokens) == (100, 15)
    assert merged.costs == known.costs
    assert merged.status == "lower_bound"
    assert "input_tokens is unavailable in part of the aggregate; total is a lower bound" in merged.warnings
    assert "cost:provider.cost is unavailable in part of the aggregate; total is a lower bound" in merged.warnings


def test_merge_preserves_request_coordinates_and_aggregates_native_cost_units():
    first = UsageSummary.from_requests(
        [
            RequestUsage(
                input_tokens=20,
                output_tokens=0,
                costs=(UsageCost(0.002, "provider_monetary", "provider.cost"),),
            )
        ],
        source="provider_otel",
        complete=False,
        is_lower_bound=True,
    ).with_context(attempt=0)
    second = UsageSummary.from_requests(
        [
            RequestUsage(
                input_tokens=100,
                output_tokens=50,
                costs=(UsageCost(0.02, "provider_monetary", "provider.cost"),),
            )
        ],
        source="provider_otel",
        complete=True,
    ).with_context(attempt=1, continuation_round=2)

    merged = first.merge(second)

    assert (merged.input_tokens, merged.output_tokens) == (120, 50)
    assert merged.costs == (UsageCost(0.022, "provider_monetary", "provider.cost"),)
    assert merged.status == "lower_bound"
    assert [request.attempt for request in merged.requests] == [0, 1]
    assert merged.requests[1].continuation_round == 2
    assert UsageSummary.from_dict(merged.to_dict()) == merged


def test_invalid_numbers_remain_unavailable_instead_of_becoming_zero():
    usage = UsageSummary.from_dict(
        {
            "available": True,
            "complete": False,
            "is_lower_bound": True,
            "input_tokens": -1,
            "output_tokens": float("nan"),
            "model_time_secs": float("inf"),
        }
    )

    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.model_time_secs is None
    assert usage.status == "lower_bound"


def test_impossible_subset_totals_are_preserved_but_flagged():
    usage = UsageSummary.from_requests(
        [
            RequestUsage(
                input_tokens=100,
                output_tokens=20,
                cache_read_input_tokens=90,
                cache_write_input_tokens=20,
                reasoning_output_tokens=25,
            )
        ],
        source="test",
        complete=True,
    )

    assert usage.input_tokens == 100
    assert usage.output_tokens == 20
    assert usage.status == "incomplete"
    assert usage.warnings == (
        "cache token total exceeds input token total",
        "reasoning token total exceeds output token total",
    )
