from evals.statistics import summarize_results, wilson_interval


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
