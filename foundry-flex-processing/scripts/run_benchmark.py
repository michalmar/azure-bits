from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any
from urllib import request


DEFAULT_PROMPT = (
    "Explain in practical terms when a software team should choose Flex processing "
    "instead of Standard processing. Include one concrete example and one reason not to use Flex."
)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(fraction * len(ordered)) - 1, 0)
    return round(ordered[index], 1)


def tier_aggregate(runs: list[dict[str, Any]], tier: str) -> dict[str, Any]:
    results = [run[tier] for run in runs]
    successful = [result for result in results if result.get("ok")]
    totals = [result["latency"]["totalMs"] for result in successful]
    first_tokens = [result["latency"]["timeToFirstTokenMs"] for result in successful]
    return {
        "totalRuns": len(results),
        "successfulRuns": len(successful),
        "totalMs": {"p50": percentile(totals, 0.5), "p95": percentile(totals, 0.95)},
        "timeToFirstTokenMs": {
            "p50": percentile(first_tokens, 0.5),
            "p95": percentile(first_tokens, 0.95),
        },
        "averageCost": round(statistics.fmean(result["cost"]["amount"] for result in successful), 10)
        if successful
        else None,
        "averageOutputTokens": round(
            statistics.fmean(result["usage"]["output_tokens"] for result in successful), 1
        )
        if successful
        else None,
        "totalRetries": sum(max(int(result.get("attempts", 1)) - 1, 0) for result in results),
        "processedTierCounts": {
            processed_tier: sum(
                1 for result in successful if result.get("processedTier") == processed_tier
            )
            for processed_tier in sorted(
                {str(result.get("processedTier") or "unknown") for result in successful}
            )
        },
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    standard = tier_aggregate(runs, "standard")
    flex = tier_aggregate(runs, "flex")
    priority = tier_aggregate(runs, "priority")
    triples = [
        run
        for run in runs
        if run["standard"].get("ok") and run["flex"].get("ok") and run["priority"].get("ok")
    ]
    standard_median = standard["totalMs"]["p50"]
    flex_median = flex["totalMs"]["p50"]
    latency_delta = (
        ((flex_median - standard_median) / standard_median) * 100
        if standard_median and flex_median is not None
        else 0
    )
    flex_savings = [
        ((run["standard"]["cost"]["amount"] - run["flex"]["cost"]["amount"]) / run["standard"]["cost"]["amount"])
        * 100
        for run in triples
        if run["standard"]["cost"]["amount"]
    ]
    priority_median = priority["totalMs"]["p50"]
    priority_latency_delta = (
        ((priority_median - standard_median) / standard_median) * 100
        if standard_median and priority_median is not None
        else 0
    )
    return {
        "standard": standard,
        "flex": flex,
        "priority": priority,
        "comparison": {
            "successfulTriples": len(triples),
            "flexMedianLatencyDeltaPercent": round(latency_delta, 1),
            "priorityMedianLatencyDeltaPercent": round(priority_latency_delta, 1),
            "flexAverageCostSavingsPercent": (
                round(statistics.fmean(flex_savings), 1) if flex_savings else 0
            ),
        },
    }


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(result)
    sanitized.pop("responseId", None)
    return sanitized


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture repeatable Standard, Flex, and Priority benchmark results."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8877")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--max-output-tokens", type=int, default=400)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "static" / "results.json",
    )
    args = parser.parse_args()
    started_at = datetime.now(UTC).isoformat()
    captured: list[dict[str, Any]] = []
    pricing = None
    model = None
    priority_deployment = None
    for index in range(1, args.runs + 1):
        response = post_json(
            f"{args.base_url.rstrip('/')}/api/compare",
            {"prompt": args.prompt, "max_output_tokens": args.max_output_tokens},
            timeout=1000,
        )
        pricing = response["pricing"]
        model = response["model"]
        priority_deployment = response["priorityDeployment"]
        captured.append(
            {
                "run": index,
                "capturedAt": datetime.now(UTC).isoformat(),
                "wallClockMs": response["wallClockMs"],
                "standard": public_result(response["results"]["standard"]),
                "flex": public_result(response["results"]["flex"]),
                "priority": public_result(response["results"]["priority"]),
            }
        )
        print(
            f"Run {index}/{args.runs}: "
            f"standard={captured[-1]['standard'].get('latency', {}).get('totalMs', 'failed')}ms, "
            f"flex={captured[-1]['flex'].get('latency', {}).get('totalMs', 'failed')}ms",
            f", priority={captured[-1]['priority'].get('latency', {}).get('totalMs', 'failed')}ms",
            flush=True,
        )
        if index < args.runs:
            time.sleep(2)
    output = {
        "schemaVersion": 2,
        "priorityDeployment": priority_deployment,
        "model": model,
        "prompt": args.prompt,
        "maxOutputTokens": args.max_output_tokens,
        "runCount": args.runs,
        "startedAt": started_at,
        "completedAt": datetime.now(UTC).isoformat(),
        "pricing": pricing,
        "aggregate": aggregate(captured),
        "runs": captured,
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
