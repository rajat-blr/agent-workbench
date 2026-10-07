from evals.statistics import (
    exact_mcnemar,
    summarize_results,
    token_usage,
    wilson_interval,
)


def test_results_use_latest_retry_without_overwriting_history() -> None:
    attempts = [
        {
            "case_revision_id": 1,
            "config_snapshot_id": 10,
            "sample_index": 0,
            "retry_index": 0,
            "outcome": "fail",
        },
        {
            "case_revision_id": 1,
            "config_snapshot_id": 10,
            "sample_index": 0,
            "retry_index": 1,
            "outcome": "pass",
        },
    ]

    results = summarize_results(attempts, [10])

    assert results["configurations"][0]["passed"] == 1
    assert results["configurations"][0]["failed"] == 0


def test_wilson_interval_and_paired_summary() -> None:
    low, high = wilson_interval(5, 10)
    assert 0.23 < low < 0.24
    assert 0.76 < high < 0.77
    attempts = []
    for case_id in range(1, 7):
        attempts.extend(
            [
                {
                    "case_revision_id": case_id,
                    "sample_index": 0,
                    "config_snapshot_id": 10,
                    "outcome": "fail",
                },
                {
                    "case_revision_id": case_id,
                    "sample_index": 0,
                    "config_snapshot_id": 20,
                    "outcome": "pass",
                },
            ]
        )
    attempts.append(
        {
            "case_revision_id": 7,
            "sample_index": 0,
            "config_snapshot_id": 10,
            "outcome": "infra_error",
        }
    )
    result = summarize_results(attempts, [10, 20])
    assert result["configurations"][0]["infrastructure_errors"] == 1
    assert result["paired"]["b_only_pass"] == 6
    assert result["verdict"] == "configuration_b_better"


def test_inference_requires_final_independent_case_pairs() -> None:
    assert exact_mcnemar(0, 5) == 0.0625
    attempts = [
        {
            "id": case * 2 + config,
            "case_revision_id": case,
            "sample_index": 0,
            "config_snapshot_id": config,
            "outcome": "pass" if config == 2 else "fail",
        }
        for case in range(6)
        for config in (1, 2)
    ]
    partial = summarize_results(attempts, [1, 2], is_final=False)
    assert partial["verdict"] == "inconclusive"
    assert partial["paired"]["p_value"] is None
    repeated = summarize_results(
        [dict(row, sample_index=1) for row in attempts], [1, 2]
    )
    assert repeated["verdict"] == "inconclusive"
    assert repeated["paired"]["inference_available"] is False
    assert all(pair["category"] == "improved" for pair in partial["comparisons"])


def test_usage_and_metrics_distinguish_unknown_from_zero() -> None:
    usage = token_usage(
        [
            {"usage": {"input_tokens": 4, "output_tokens": 0}},
            {
                "usage": {
                    "input_tokens": 6,
                    "output_tokens": False,
                    "cached_input_tokens": -1,
                }
            },
            {"usage": None},
        ]
    )
    assert usage == {
        "input_tokens": 10,
        "output_tokens": 0,
        "cached_input_tokens": None,
        "reasoning_output_tokens": None,
    }
    result = summarize_results(
        [
            {
                "case_revision_id": case,
                "config_snapshot_id": 1,
                "sample_index": 0,
                "outcome": "pass",
                "agent_duration_ms": duration,
                **usage,
            }
            for case, duration in ((1, 100), (2, 300))
        ],
        [1],
    )["configurations"][0]
    assert result["durations_ms"]["agent"]["median"] == 200
    assert result["tokens"]["input_tokens"] == {"total": 20, "observed": 2}
    assert result["tokens"]["output_tokens"]["total"] == 0
    assert result["tokens"]["cached_input_tokens"]["total"] is None
