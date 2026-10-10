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


def test_inference_requires_final_case_pairs_not_sample_index_zero() -> None:
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
    assert repeated["verdict"] == "configuration_b_better"
    assert repeated["paired"]["inference_available"] is True
    assert all(pair["category"] == "improved" for pair in partial["comparisons"])


def test_repeating_one_case_does_not_create_independent_evidence():
    attempts = [
        {
            "case_revision_id": 1,
            "sample_index": sample,
            "config_snapshot_id": config,
            "outcome": "pass" if config == 2 else "fail",
        }
        for sample in range(100)
        for config in (1, 2)
    ]
    result = summarize_results(attempts, [1, 2])
    assert result["paired"]["case_count"] == 1
    assert result["paired"]["sample_count"] == 100
    assert result["paired"]["p_value"] is None
    assert result["verdict"] == "inconclusive"
    assert result["configurations"][0]["confidence_low"] is None


def test_equal_case_weights_and_bootstrap_do_not_treat_attempts_as_independent():
    attempts = [
        {
            "case_revision_id": 1,
            "sample_index": sample,
            "config_snapshot_id": 1,
            "outcome": "pass",
        }
        for sample in range(99)
    ] + [
        {
            "case_revision_id": 2,
            "sample_index": 0,
            "config_snapshot_id": 1,
            "outcome": "fail",
        }
    ]
    config = summarize_results(attempts, [1])["configurations"][0]
    assert config["pass_rate"] == 0.5
    assert config["attempt_pass_rate"] == 0.99
    assert config["case_count"] == 2
    assert config["confidence_low"] == 0
    assert config["confidence_high"] == 1


def test_five_cases_cannot_become_significant_by_repeating_samples():
    rows = [
        {
            "case_revision_id": case,
            "sample_index": sample,
            "config_snapshot_id": config,
            "outcome": "pass" if config == 2 else "fail",
        }
        for case in range(5)
        for sample in range(10)
        for config in (1, 2)
    ]
    result = summarize_results(rows, [1, 2])
    assert result["paired"]["p_value"] == 0.0625
    assert result["verdict"] == "inconclusive"
    assert result["paired"]["case_count"] == 5


def test_paired_case_rates_use_only_matched_evaluable_samples():
    rows = [
        {
            "case_revision_id": 1,
            "sample_index": sample,
            "config_snapshot_id": config,
            "outcome": outcome,
        }
        for sample, config, outcome in [
            (0, 1, "fail"),
            (0, 2, "pass"),
            (1, 1, "pass"),
            (1, 2, "timeout"),
        ]
    ]
    result = summarize_results(rows, [1, 2])
    assert result["paired"]["case_comparisons"][0]["difference"] == 1
    assert result["paired"]["case_comparisons"][0]["paired_samples"] == 1
    assert result["configurations"][1]["case_pass_rates"][0]["excluded"] == 1


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
