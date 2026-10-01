from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


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
    attempts: list[dict[str, Any]], config_ids: list[int]
) -> dict[str, Any]:
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
            }
        )
    paired = {"a_only_pass": 0, "b_only_pass": 0, "both_pass": 0, "both_fail": 0}
    if len(config_ids) == 2:
        indexed = {
            (
                row["case_revision_id"],
                row["sample_index"],
                row["config_snapshot_id"],
            ): row
            for row in attempts
            if row["outcome"] in {"pass", "fail"}
        }
        pairs = {(case_id, sample) for case_id, sample, _config in indexed}
        for case_id, sample in pairs:
            left = indexed.get((case_id, sample, config_ids[0]))
            right = indexed.get((case_id, sample, config_ids[1]))
            if not left or not right:
                continue
            if left["outcome"] == "pass" and right["outcome"] == "fail":
                paired["a_only_pass"] += 1
            elif left["outcome"] == "fail" and right["outcome"] == "pass":
                paired["b_only_pass"] += 1
            elif left["outcome"] == "pass":
                paired["both_pass"] += 1
            else:
                paired["both_fail"] += 1
    discordant = paired["a_only_pass"] + paired["b_only_pass"]
    verdict = "inconclusive"
    if discordant >= 5 and paired["b_only_pass"] >= 2 * max(1, paired["a_only_pass"]):
        verdict = "configuration_b_better"
    elif discordant >= 5 and paired["a_only_pass"] >= 2 * max(1, paired["b_only_pass"]):
        verdict = "configuration_a_better"
    return {"configurations": configurations, "paired": paired, "verdict": verdict}
