from __future__ import annotations

import math
import random
from collections import defaultdict
from functools import lru_cache
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


@lru_cache(maxsize=256)
def case_bootstrap(values: tuple[float, ...]) -> tuple[float | None, float | None]:
    """Percentile interval for an equal-weight case mean, never pooled attempts."""
    if len(values) < 2:
        return None, None
    rng = random.Random(20261009)  # noqa: S311 -- deterministic statistical resampling, not secrets
    means = sorted(
        sum(rng.choices(values, k=len(values))) / len(values) for _ in range(4096)
    )
    return means[102], means[3993]


def case_rates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["case_revision_id"]].append(row)
    result = []
    for case_id, samples in sorted(grouped.items()):
        passed = sum(row.get("outcome") == "pass" for row in samples)
        failed = sum(row.get("outcome") == "fail" for row in samples)
        total = passed + failed
        result.append(
            {
                "case_revision_id": case_id,
                "passed": passed,
                "failed": failed,
                "evaluable": total,
                "excluded": len(samples) - total,
                "pass_rate": passed / total if total else None,
            }
        )
    return result


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
        per_case = case_rates(rows)
        rates = tuple(
            row["pass_rate"] for row in per_case if row["pass_rate"] is not None
        )
        low, high = case_bootstrap(rates)
        configurations.append(
            {
                "config_snapshot_id": config_id,
                "passed": passed,
                "failed": failed,
                "infrastructure_errors": infrastructure_errors,
                "evaluable": total,
                "pass_rate": sum(rates) / len(rates) if rates else None,
                "attempt_pass_rate": passed / total if total else None,
                "case_count": len(rates),
                "case_pass_rates": per_case,
                "confidence_low": low,
                "confidence_high": high,
                "confidence_method": "case_bootstrap_percentile_4096",
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
    paired_cases: dict[int, list[tuple[bool, bool]]] = defaultdict(list)
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
            paired_cases[case_id].append((outcomes[0] == "pass", outcomes[1] == "pass"))
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
    case_comparisons = [
        {
            "case_revision_id": case_id,
            "paired_samples": len(samples),
            "a_pass_rate": sum(left for left, _ in samples) / len(samples),
            "b_pass_rate": sum(right for _, right in samples) / len(samples),
            "difference": sum(int(right) - int(left) for left, right in samples)
            / len(samples),
        }
        for case_id, samples in sorted(paired_cases.items())
    ]
    deltas = tuple(row["difference"] for row in case_comparisons)
    improved_cases = sum(delta > 0 for delta in deltas)
    regressed_cases = sum(delta < 0 for delta in deltas)
    inference_available = len(config_ids) == 2 and is_final and len(deltas) >= 2
    p_value = (
        exact_mcnemar(regressed_cases, improved_cases) if inference_available else None
    )
    verdict = "inconclusive"
    if (
        p_value is not None
        and p_value < 0.05
        and improved_cases > regressed_cases
        and sum(deltas) > 0
    ):
        verdict = "configuration_b_better"
    elif (
        p_value is not None
        and p_value < 0.05
        and regressed_cases > improved_cases
        and sum(deltas) < 0
    ):
        verdict = "configuration_a_better"
    low, high = case_bootstrap(deltas)
    summary = f"{len(deltas)} evaluable cases ({paired_count} matched sample pairs): {improved_cases} improved and {regressed_cases} regressed cases for B versus A."
    if len(config_ids) != 2:
        summary = "Single configuration: no paired comparison is available."
    elif paired_count:
        difference = 100 * sum(deltas) / len(deltas)
        summary += f" Equal-weight case pass-rate difference: {difference:+.1f} percentage points."
    if len(config_ids) != 2:
        pass
    elif not is_final:
        summary += " Results are partial; the verdict remains inconclusive."
    elif not paired_count:
        summary += " No paired pass/fail outcomes are available."
    elif verdict == "inconclusive":
        summary += " Evidence is insufficient to distinguish the configurations."
    else:
        summary += " The case-level sign test supports the observed direction on evaluable cases in this suite, not a general model ranking."
    warnings = [
        "Cases, not attempts, are the analysis unit; related cases may still be dependent.",
        "Case-bootstrap intervals describe case variability and can collapse at uniform outcomes; they do not establish significance.",
        "Inference is conditional on matched pass/fail samples; missing, cancelled and infrastructure outcomes are excluded, not counted as failures.",
    ]
    if improved_cases + regressed_cases < 6 and len(config_ids) == 2:
        warnings.append(
            "Fewer than six non-tied cases cannot reach two-sided sign-test p < 0.05, regardless of repeated sample count."
        )
    return {
        "configurations": configurations,
        "paired": {
            **paired,
            "sample_count": paired_count,
            "discordant": discordant,
            "p_value": p_value,
            "inference_available": inference_available,
            "method": "case_level_exact_sign_test",
            "case_count": len(deltas),
            "improved_cases": improved_cases,
            "regressed_cases": regressed_cases,
            "mean_difference": sum(deltas) / len(deltas) if deltas else None,
            "confidence_low": low,
            "confidence_high": high,
            "case_comparisons": case_comparisons,
        },
        "comparisons": comparisons,
        "verdict": verdict,
        "verdict_summary": summary,
        "is_final": is_final,
        "analysis_unit": "case_revision",
        "warnings": warnings,
    }
