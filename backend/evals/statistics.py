from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any

TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


def token_usage(payloads: list[dict[str, Any]]) -> dict[str, int | None]:
    totals: dict[str, int | None] = dict.fromkeys(TOKEN_FIELDS)
    for payload in payloads:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in TOKEN_FIELDS:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[key] = (totals[key] or 0) + value
    return totals


def exact_mcnemar(a_only: int, b_only: int) -> float:
    discordant = a_only + b_only
    if not discordant:
        return 1.0
    tail = sum(math.comb(discordant, index) for index in range(min(a_only, b_only) + 1))
    return min(1.0, 2 * tail / (2**discordant))


def wilson_interval(
    passed: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = passed / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt(
        (proportion * (1 - proportion) + z * z / (4 * total)) / total
    )
    return (
        max(0.0, (centre - margin) / denominator),
        min(1.0, (centre + margin) / denominator),
    )


def summarize_results(
    attempts: list[dict[str, Any]], config_ids: list[int], *, is_final: bool = True
) -> dict[str, Any]:
    latest: dict[tuple[int, int, int], dict[str, Any]] = {}
    for attempt in attempts:
        identity = (
            attempt["case_revision_id"],
            attempt["config_snapshot_id"],
            attempt["sample_index"],
        )
        current = latest.get(identity)
        if current is None or attempt.get("retry_index", 0) > current.get(
            "retry_index", 0
        ):
            latest[identity] = attempt
    attempts = list(latest.values())
    by_config: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        by_config[attempt["config_snapshot_id"]].append(attempt)
    configurations = []
    for config_id in config_ids:
        rows = by_config[config_id]
        passed = sum(row["outcome"] == "pass" for row in rows)
        failed = sum(row["outcome"] == "fail" for row in rows)
        infrastructure_errors = sum(
            row["outcome"] in {"infra_error", "timeout", "invalid_case"} for row in rows
        )
        total = passed + failed
        low, high = wilson_interval(passed, total)
        configurations.append(
            {
                "config_snapshot_id": config_id,
                "passed": passed,
                "failed": failed,
                "infrastructure_errors": infrastructure_errors,
                "evaluable": total,
                "pass_rate": passed / total if total else None,
                "confidence_low": low if total else None,
                "confidence_high": high if total else None,
                "outcome_counts": {
                    outcome: sum(row.get("outcome") == outcome for row in rows)
                    for outcome in (
                        "pass",
                        "fail",
                        "infra_error",
                        "timeout",
                        "cancelled",
                        "invalid_case",
                    )
                },
                "pending": sum(
                    row.get("status") in {"queued", "running"} for row in rows
                ),
                "durations_ms": {
                    stage: {
                        "median": median(values) if values else None,
                        "min": min(values) if values else None,
                        "max": max(values) if values else None,
                        "observed": len(values),
                    }
                    for stage in ("setup", "agent", "scoring")
                    for values in [
                        [
                            row[f"{stage}_duration_ms"]
                            for row in rows
                            if row.get(f"{stage}_duration_ms") is not None
                        ]
                    ]
                },
                "tokens": {
                    key: {
                        "total": sum(values) if values else None,
                        "observed": len(values),
                    }
                    for key in TOKEN_FIELDS
                    for values in [
                        [row[key] for row in rows if row.get(key) is not None]
                    ]
                },
            }
        )
    paired = {"a_only_pass": 0, "b_only_pass": 0, "both_pass": 0, "both_fail": 0}
    comparisons = []
    repeated_samples = any(row["sample_index"] != 0 for row in attempts)
    if len(config_ids) == 2:
        indexed = {
            (
                row["case_revision_id"],
                row["sample_index"],
                row["config_snapshot_id"],
            ): row
            for row in attempts
        }
        pairs = {(case_id, sample) for case_id, sample, _config in indexed}
        for case_id, sample in sorted(pairs):
            left = indexed.get((case_id, sample, config_ids[0]))
            right = indexed.get((case_id, sample, config_ids[1]))
            outcomes = [row.get("outcome") if row else None for row in (left, right)]
            category = "unpaired"
            if any(
                outcome in {"infra_error", "timeout", "invalid_case"}
                for outcome in outcomes
            ):
                category = "infrastructure"
            elif any(
                row and row.get("status") in {"queued", "running"}
                for row in (left, right)
            ):
                category = "pending"
            elif all(outcome in {"pass", "fail"} for outcome in outcomes):
                category = "unchanged"
            comparisons.append(
                {
                    "case_revision_id": case_id,
                    "sample_index": sample,
                    "category": category,
                    "attempt_ids": [
                        row["id"] for row in (left, right) if row and "id" in row
                    ],
                }
            )
            if category != "unchanged":
                continue
            if outcomes == ["pass", "fail"]:
                paired["a_only_pass"] += 1
                comparisons[-1]["category"] = "regressed"
            elif outcomes == ["fail", "pass"]:
                paired["b_only_pass"] += 1
                comparisons[-1]["category"] = "improved"
            elif outcomes[0] == "pass":
                paired["both_pass"] += 1
            else:
                paired["both_fail"] += 1
    discordant = paired["a_only_pass"] + paired["b_only_pass"]
    paired_count = sum(paired.values())
    inference_available = (
        len(config_ids) == 2 and not repeated_samples and is_final and paired_count > 0
    )
    p_value = (
        exact_mcnemar(paired["a_only_pass"], paired["b_only_pass"])
        if inference_available
        else None
    )
    verdict = "inconclusive"
    if (
        p_value is not None
        and p_value < 0.05
        and paired["b_only_pass"] > paired["a_only_pass"]
    ):
        verdict = "configuration_b_better"
    elif (
        p_value is not None
        and p_value < 0.05
        and paired["a_only_pass"] > paired["b_only_pass"]
    ):
        verdict = "configuration_a_better"
    summary = f"{paired_count} evaluable pairs: {paired['b_only_pass']} improvements and {paired['a_only_pass']} regressions for B versus A."
    if len(config_ids) != 2:
        summary = "Single configuration: no paired comparison is available."
    elif paired_count:
        difference = (
            100 * (paired["b_only_pass"] - paired["a_only_pass"]) / paired_count
        )
        summary += f" Paired pass-rate difference: {difference:+.1f} percentage points."
    if len(config_ids) != 2:
        pass
    elif not is_final:
        summary += " Results are partial; the verdict remains inconclusive."
    elif repeated_samples:
        summary += " Repeated samples are descriptive; case-level uncertainty is not yet available."
    elif not paired_count:
        summary += " No paired pass/fail outcomes are available."
    elif verdict == "inconclusive":
        summary += " Evidence is insufficient to distinguish the configurations."
    else:
        summary += " The paired outcomes support the observed direction; consider the size of the difference before choosing."
    return {
        "configurations": configurations,
        "paired": {
            **paired,
            "sample_count": paired_count,
            "discordant": discordant,
            "p_value": p_value,
            "inference_available": inference_available,
        },
        "comparisons": comparisons,
        "verdict": verdict,
        "verdict_summary": summary,
        "is_final": is_final,
    }
