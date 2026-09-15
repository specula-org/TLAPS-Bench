"""Provider-neutral model usage records for evaluator results."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any


def nonnegative_int(value: object) -> int | None:
    """Return a finite non-negative integer, preserving unavailable values."""

    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def nonnegative_float(value: object) -> float | None:
    """Return a finite non-negative float, preserving unavailable values."""

    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 and math.isfinite(parsed) else None


@dataclass(frozen=True)
class UsageCost:
    """One provider-reported or estimated cost in its native unit."""

    amount: float
    unit: str
    source: str

    @classmethod
    def from_dict(cls, value: object) -> UsageCost | None:
        if not isinstance(value, dict):
            return None
        amount = nonnegative_float(value.get("amount"))
        unit = value.get("unit")
        source = value.get("source")
        if amount is None or not isinstance(unit, str) or not unit or not isinstance(source, str) or not source:
            return None
        return cls(amount, unit, source)

    def to_dict(self) -> dict[str, object]:
        return {"amount": self.amount, "unit": self.unit, "source": self.source}


@dataclass(frozen=True)
class RequestUsage:
    """Usage for one completed model request.

    Cache tokens are classifications within input usage, and reasoning tokens
    are a classification within output usage. They must not be added to the
    input/output totals a second time.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    duration_secs: float | None = None
    server_duration: float | None = None
    finish_reasons: tuple[str, ...] = ()
    request_id: str | None = None
    provider_request_id: str | None = None
    interaction_id: str | None = None
    turn_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    attempt: int | None = None
    continuation_round: int | None = None
    costs: tuple[UsageCost, ...] = ()

    @classmethod
    def from_dict(cls, value: object) -> RequestUsage | None:
        if not isinstance(value, dict):
            return None

        def text(name: str) -> str | None:
            candidate = value.get(name)
            return candidate if isinstance(candidate, str) and candidate else None

        raw_reasons = value.get("finish_reasons")
        reasons = (
            tuple(reason for reason in raw_reasons if isinstance(reason, str) and reason)
            if isinstance(raw_reasons, list)
            else ()
        )
        raw_costs = value.get("costs")
        costs = (
            tuple(cost for item in raw_costs if (cost := UsageCost.from_dict(item)) is not None)
            if isinstance(raw_costs, list)
            else ()
        )
        return cls(
            input_tokens=nonnegative_int(value.get("input_tokens")),
            output_tokens=nonnegative_int(value.get("output_tokens")),
            cache_read_input_tokens=nonnegative_int(value.get("cache_read_input_tokens")),
            cache_write_input_tokens=nonnegative_int(value.get("cache_write_input_tokens")),
            reasoning_output_tokens=nonnegative_int(value.get("reasoning_output_tokens")),
            requested_model=text("requested_model"),
            resolved_model=text("resolved_model"),
            provider=text("provider"),
            endpoint=text("endpoint"),
            duration_secs=nonnegative_float(value.get("duration_secs")),
            server_duration=nonnegative_float(value.get("server_duration")),
            finish_reasons=reasons,
            request_id=text("request_id"),
            provider_request_id=text("provider_request_id"),
            interaction_id=text("interaction_id"),
            turn_id=text("turn_id"),
            trace_id=text("trace_id"),
            span_id=text("span_id"),
            attempt=nonnegative_int(value.get("attempt")),
            continuation_round=nonnegative_int(value.get("continuation_round")),
            costs=costs,
        )

    def with_context(self, *, attempt: int | None = None, continuation_round: int | None = None) -> RequestUsage:
        """Attach runner-owned attempt/continuation coordinates."""

        return replace(
            self,
            attempt=self.attempt if attempt is None else attempt,
            continuation_round=self.continuation_round if continuation_round is None else continuation_round,
        )

    def to_dict(self) -> dict[str, object]:
        values: dict[str, Any] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "duration_secs": self.duration_secs,
            "server_duration": self.server_duration,
            "request_id": self.request_id,
            "provider_request_id": self.provider_request_id,
            "interaction_id": self.interaction_id,
            "turn_id": self.turn_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "attempt": self.attempt,
            "continuation_round": self.continuation_round,
        }
        result = {key: value for key, value in values.items() if value is not None}
        if self.finish_reasons:
            result["finish_reasons"] = list(self.finish_reasons)
        if self.costs:
            result["costs"] = [cost.to_dict() for cost in self.costs]
        return result


_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_write_input_tokens",
    "reasoning_output_tokens",
)


def _sum_optional(values: list[int | float | None]) -> int | float | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _strict_nonnegative_int(value: object) -> int | None:
    """Validate a provider aggregate without coercing protocol values."""

    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _strict_nonnegative_float(value: object) -> float | None:
    """Validate a provider duration aggregate without coercion."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    parsed = float(value)
    return parsed if parsed >= 0 and math.isfinite(parsed) else None


def _aggregate_costs(costs: tuple[UsageCost, ...] | list[UsageCost]) -> tuple[UsageCost, ...]:
    totals: dict[tuple[str, str], float] = {}
    for cost in costs:
        amount = nonnegative_float(cost.amount)
        if amount is None or not cost.unit or not cost.source:
            continue
        key = (cost.unit, cost.source)
        totals[key] = totals.get(key, 0.0) + amount
    return tuple(
        UsageCost(amount=amount, unit=unit, source=source) for (unit, source), amount in sorted(totals.items())
    )


@dataclass(frozen=True)
class UsageSummary:
    """Serializable usage totals plus optional per-request evidence."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    model_requests: int | None = None
    model_time_secs: float | None = None
    costs: tuple[UsageCost, ...] = ()
    requests: tuple[RequestUsage, ...] = ()
    sources: tuple[str, ...] = ()
    runtime_versions: tuple[str, ...] = ()
    available: bool = True
    complete: bool = False
    is_lower_bound: bool = False
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: object) -> UsageSummary:
        """Read schema v1 data for runner-side continuation aggregation."""

        if not isinstance(value, dict):
            return cls(available=False, warnings=("invalid structured usage record",))

        def strings(name: str) -> tuple[str, ...]:
            raw = value.get(name)
            if not isinstance(raw, list):
                return ()
            return tuple(item for item in raw if isinstance(item, str) and item)

        raw_costs = value.get("costs")
        costs = (
            tuple(cost for item in raw_costs if (cost := UsageCost.from_dict(item)) is not None)
            if isinstance(raw_costs, list)
            else ()
        )
        raw_requests = value.get("requests")
        requests = (
            tuple(request for item in raw_requests if (request := RequestUsage.from_dict(item)) is not None)
            if isinstance(raw_requests, list)
            else ()
        )
        return cls(
            input_tokens=nonnegative_int(value.get("input_tokens")),
            output_tokens=nonnegative_int(value.get("output_tokens")),
            cache_read_input_tokens=nonnegative_int(value.get("cache_read_input_tokens")),
            cache_write_input_tokens=nonnegative_int(value.get("cache_write_input_tokens")),
            reasoning_output_tokens=nonnegative_int(value.get("reasoning_output_tokens")),
            model_requests=nonnegative_int(value.get("model_requests")),
            model_time_secs=nonnegative_float(value.get("model_time_secs")),
            costs=costs,
            requests=requests,
            sources=strings("sources"),
            runtime_versions=strings("runtime_versions"),
            available=value.get("available") is True,
            complete=value.get("complete") is True,
            is_lower_bound=value.get("is_lower_bound") is True,
            warnings=strings("warnings"),
        )

    @classmethod
    def from_legacy(cls, input_tokens: int, output_tokens: int, *, source: str) -> UsageSummary:
        """Adapt the original two-token backend contract without breaking it."""

        return cls(
            input_tokens=nonnegative_int(input_tokens),
            output_tokens=nonnegative_int(output_tokens),
            sources=(source,),
            available=True,
            complete=False,
        )

    @classmethod
    def from_requests(
        cls,
        requests: list[RequestUsage] | tuple[RequestUsage, ...],
        *,
        source: str,
        complete: bool,
        is_lower_bound: bool = False,
        available: bool = True,
        runtime_versions: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        totals: dict[str, object] | None = None,
    ) -> UsageSummary:
        """Build a summary, optionally using provider aggregate totals."""

        request_tuple = tuple(requests)
        derived: dict[str, int | float | None] = {
            field: _sum_optional([getattr(request, field) for request in request_tuple]) for field in _TOKEN_FIELDS
        }
        derived["model_requests"] = len(request_tuple)
        derived["model_time_secs"] = _sum_optional([request.duration_secs for request in request_tuple])
        provider_total_fields: set[str] = set()
        invalid_total_fields: list[str] = []
        if totals:
            for key in (*_TOKEN_FIELDS, "model_requests"):
                if key not in totals:
                    continue
                value = _strict_nonnegative_int(totals[key])
                if value is None:
                    invalid_total_fields.append(key)
                else:
                    derived[key] = value
                    provider_total_fields.add(key)
            if "model_time_secs" in totals:
                model_time = _strict_nonnegative_float(totals["model_time_secs"])
                if model_time is None:
                    invalid_total_fields.append("model_time_secs")
                else:
                    derived["model_time_secs"] = model_time
                    provider_total_fields.add("model_time_secs")
        request_costs = tuple(cost for request in request_tuple for cost in request.costs)
        aggregate_costs = request_costs
        if totals and isinstance(totals.get("costs"), (list, tuple)):
            aggregate_costs = tuple(cost for cost in totals["costs"] if isinstance(cost, UsageCost))
        validation_warnings: list[str] = []
        partial_fields: list[str] = []
        for field in (*_TOKEN_FIELDS, "model_time_secs"):
            values = [
                getattr(request, field if field != "model_time_secs" else "duration_secs") for request in request_tuple
            ]
            has_provider_total = field in provider_total_fields
            if (
                values
                and not has_provider_total
                and any(value is None for value in values)
                and any(value is not None for value in values)
            ):
                partial_fields.append(field)

        authoritative_cost_keys = {
            (cost.unit, cost.source)
            for cost in aggregate_costs
            if totals and isinstance(totals.get("costs"), (list, tuple))
        }
        request_cost_keys = {(cost.unit, cost.source) for request in request_tuple for cost in request.costs}
        for unit, cost_source in sorted(request_cost_keys - authoritative_cost_keys):
            covered = sum(
                any(cost.unit == unit and cost.source == cost_source for cost in request.costs)
                for request in request_tuple
            )
            if 0 < covered < len(request_tuple):
                partial_fields.append(f"cost:{cost_source}")
        core_fields_missing_everywhere: list[str] = []
        empty_exactness_errors: list[str] = []
        if complete and derived["model_requests"]:
            for field in ("input_tokens", "output_tokens"):
                values = [getattr(request, field) for request in request_tuple]
                if field not in provider_total_fields and (not values or all(value is None for value in values)):
                    core_fields_missing_everywhere.append(field)
        elif complete:
            for field in ("input_tokens", "output_tokens"):
                if field not in provider_total_fields or derived[field] != 0:
                    empty_exactness_errors.append(field)
            if "model_requests" not in provider_total_fields or derived["model_requests"] != 0:
                empty_exactness_errors.append("model_requests")

        validation_warnings.extend(
            f"{field} is missing for some model requests; total is a lower bound" for field in partial_fields
        )
        validation_warnings.extend(
            f"{field} is unavailable for every model request; total is a lower bound"
            for field in core_fields_missing_everywhere
        )
        validation_warnings.extend(
            f"invalid authoritative {field} total; provider aggregates must use non-negative numeric values"
            for field in invalid_total_fields
        )
        if empty_exactness_errors:
            validation_warnings.append(
                "an exact zero-request summary requires authoritative zero input_tokens, "
                "output_tokens, and model_requests totals"
            )
        input_total = nonnegative_int(derived["input_tokens"])
        cache_read_total = nonnegative_int(derived["cache_read_input_tokens"])
        cache_write_total = nonnegative_int(derived["cache_write_input_tokens"])
        known_cache_total = sum(value for value in (cache_read_total, cache_write_total) if value is not None)
        integrity_errors: list[str] = []
        if input_total is not None and known_cache_total > input_total:
            integrity_errors.append("cache token total exceeds input token total")
        output_total = nonnegative_int(derived["output_tokens"])
        reasoning_total = nonnegative_int(derived["reasoning_output_tokens"])
        if output_total is not None and reasoning_total is not None and reasoning_total > output_total:
            integrity_errors.append("reasoning token total exceeds output token total")
        validation_warnings.extend(integrity_errors)
        lower_bound_evidence = bool(partial_fields or core_fields_missing_everywhere)
        invalid_exactness = bool(invalid_total_fields or empty_exactness_errors or integrity_errors)
        return cls(
            input_tokens=input_total,
            output_tokens=output_total,
            cache_read_input_tokens=cache_read_total,
            cache_write_input_tokens=cache_write_total,
            reasoning_output_tokens=reasoning_total,
            model_requests=nonnegative_int(derived["model_requests"]),
            model_time_secs=nonnegative_float(derived["model_time_secs"]),
            costs=_aggregate_costs(aggregate_costs),
            requests=request_tuple,
            sources=(source,),
            runtime_versions=tuple(dict.fromkeys(runtime_versions)),
            available=available,
            complete=complete and not lower_bound_evidence and not invalid_exactness,
            is_lower_bound=is_lower_bound or lower_bound_evidence,
            warnings=tuple(dict.fromkeys((*warnings, *validation_warnings))),
        )

    @property
    def status(self) -> str:
        if self.complete:
            return "complete"
        if self.is_lower_bound:
            return "lower_bound"
        if not self.available:
            return "unavailable"
        return "incomplete"

    @property
    def legacy_input_tokens(self) -> int:
        return self.input_tokens or 0

    @property
    def legacy_output_tokens(self) -> int:
        return self.output_tokens or 0

    def with_context(self, *, attempt: int | None = None, continuation_round: int | None = None) -> UsageSummary:
        """Attach runner coordinates to each per-request record."""

        return replace(
            self,
            requests=tuple(
                request.with_context(attempt=attempt, continuation_round=continuation_round)
                for request in self.requests
            ),
        )

    def merge(self, other: UsageSummary) -> UsageSummary:
        """Add independent attempts/rounds without double-counting buckets."""

        partial_fields = [
            field
            for field in (*_TOKEN_FIELDS, "model_requests", "model_time_secs")
            if (getattr(self, field) is None) != (getattr(other, field) is None)
        ]
        self_cost_keys = {(cost.unit, cost.source) for cost in self.costs}
        other_cost_keys = {(cost.unit, cost.source) for cost in other.costs}
        if other.model_requests != 0:
            partial_fields.extend(f"cost:{source}" for _unit, source in sorted(self_cost_keys - other_cost_keys))
        if self.model_requests != 0:
            partial_fields.extend(f"cost:{source}" for _unit, source in sorted(other_cost_keys - self_cost_keys))
        partial_warnings = tuple(
            f"{field} is unavailable in part of the aggregate; total is a lower bound"
            for field in dict.fromkeys(partial_fields)
        )
        return UsageSummary(
            input_tokens=nonnegative_int(_sum_optional([self.input_tokens, other.input_tokens])),
            output_tokens=nonnegative_int(_sum_optional([self.output_tokens, other.output_tokens])),
            cache_read_input_tokens=nonnegative_int(
                _sum_optional([self.cache_read_input_tokens, other.cache_read_input_tokens])
            ),
            cache_write_input_tokens=nonnegative_int(
                _sum_optional([self.cache_write_input_tokens, other.cache_write_input_tokens])
            ),
            reasoning_output_tokens=nonnegative_int(
                _sum_optional([self.reasoning_output_tokens, other.reasoning_output_tokens])
            ),
            model_requests=nonnegative_int(_sum_optional([self.model_requests, other.model_requests])),
            model_time_secs=nonnegative_float(_sum_optional([self.model_time_secs, other.model_time_secs])),
            costs=_aggregate_costs((*self.costs, *other.costs)),
            requests=(*self.requests, *other.requests),
            sources=tuple(dict.fromkeys((*self.sources, *other.sources))),
            runtime_versions=tuple(dict.fromkeys((*self.runtime_versions, *other.runtime_versions))),
            available=self.available or other.available,
            complete=self.complete and other.complete and not partial_fields,
            is_lower_bound=self.is_lower_bound or other.is_lower_bound or bool(partial_fields),
            warnings=tuple(dict.fromkeys((*self.warnings, *other.warnings, *partial_warnings))),
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-native schema v1 data, keeping unavailable totals null."""

        return {
            "schema_version": 1,
            "status": self.status,
            "available": self.available,
            "complete": self.complete,
            "is_lower_bound": self.is_lower_bound,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "model_requests": self.model_requests,
            "model_time_secs": self.model_time_secs,
            "costs": [cost.to_dict() for cost in self.costs],
            "sources": list(self.sources),
            "runtime_versions": list(self.runtime_versions),
            "requests": [request.to_dict() for request in self.requests],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class TokenUsage:
    """Display-safe core token totals without converting unknown data to zero."""

    input_tokens: int | None
    output_tokens: int | None
    is_lower_bound: bool = False

    @property
    def available(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None


def result_token_usage(result: Mapping[str, object]) -> TokenUsage:
    """Read structured usage when present, falling back to legacy result fields."""

    raw_usage = result.get("usage")
    if isinstance(raw_usage, dict) and any(
        field in raw_usage for field in ("status", "available", "input_tokens", "output_tokens")
    ):
        usage = UsageSummary.from_dict(raw_usage)
        if not usage.available or usage.input_tokens is None or usage.output_tokens is None:
            return TokenUsage(None, None)
        return TokenUsage(usage.input_tokens, usage.output_tokens, usage.is_lower_bound)

    input_tokens = nonnegative_int(result.get("input_tokens"))
    output_tokens = nonnegative_int(result.get("output_tokens"))
    return TokenUsage(input_tokens, output_tokens)


def aggregate_token_usage(results: list[Mapping[str, object]]) -> TokenUsage:
    """Sum token usage only when every result has usable core-token evidence."""

    usages = [result_token_usage(result) for result in results]
    if any(not usage.available for usage in usages):
        return TokenUsage(None, None)
    return TokenUsage(
        sum(usage.input_tokens for usage in usages if usage.input_tokens is not None),
        sum(usage.output_tokens for usage in usages if usage.output_tokens is not None),
        any(usage.is_lower_bound for usage in usages),
    )


def format_token_usage(usage: TokenUsage, *, verbose: bool = False) -> str:
    """Format exact, lower-bound, and unavailable usage without ambiguity."""

    if not usage.available:
        return "unavailable"
    prefix = "at least " if verbose and usage.is_lower_bound else "≥" if usage.is_lower_bound else ""
    if verbose:
        return f"{prefix}{usage.input_tokens:,} input / {usage.output_tokens:,} output"
    return f"{prefix}{usage.input_tokens:,}/{usage.output_tokens:,}"
