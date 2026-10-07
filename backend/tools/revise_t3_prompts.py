"""Publish scope-explicit T3 revisions without changing historical inputs or rerunning agents."""

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.import_t3_live import Rpc, connection_for_process

ROOT = Path(__file__).resolve().parents[2]


def revise_t3_cases(rpc, overlay: dict) -> dict:
    catalog = {c["title"]: c for c in rpc("eval.case.list")}
    planned = []
    for item in overlay["cases"]:
        case = catalog[f"T3 Code: {item['id']}"]
        revision = case["latest_revision"]
        if revision["prompt"] not in {item["original_prompt"], item["prompt"]}:
            raise ValueError(
                "Case prompt changed independently; refusing to overwrite it"
            )
        if revision["status"] == "draft" and revision["prompt"] != item["prompt"]:
            raise ValueError("An unrelated draft exists; refusing to overwrite it")
        scope = next(s for s in revision["scorer_spec"] if s["type"] == "diff")
        if scope.get("allowed") != [item["allowed_path"]]:
            raise ValueError("Prompt scope does not match the existing grader")
        planned.append((case, item))
    revised = []
    for case, item in planned:
        revision = case["latest_revision"]
        if revision["status"] == "published" and revision["prompt"] == item["prompt"]:
            revised.append(revision["id"])
            continue
        if revision["status"] == "published":
            case = rpc(
                "eval.case.revise",
                {"case_id": case["id"], "revision_id": revision["id"]},
            )
        identity = {"case_id": case["id"], "revision_id": case["latest_revision"]["id"]}
        rpc("eval.case.update_draft", {**identity, "prompt": item["prompt"]})
        checked = rpc("eval.case.validate", identity)
        if checked["latest_revision"]["validation_status"] != "valid":
            raise RuntimeError(
                f"Validation failed for {item['id']}; draft retained, original suite unchanged"
            )
        published = rpc("eval.case.publish", identity)
        revised.append(published["latest_revision"]["id"])
    suite = next(
        s
        for s in rpc("eval.suite.list")
        if s["name"] == "T3 Code realistic regressions"
    )
    latest = suite["latest_version"]
    if (
        latest["status"] == "frozen"
        and [c["revision_id"] for c in latest["cases"]] == revised
    ):
        return {"suite": suite, "revision_ids": revised, "agent_attempts_launched": 0}
    draft = rpc(
        "eval.suite.update_draft",
        {
            "suite_id": suite["id"],
            "version_id": latest["id"],
            "case_revision_ids": revised,
        },
    )
    frozen = rpc(
        "eval.suite.freeze",
        {"suite_id": suite["id"], "version_id": draft["latest_version"]["id"]},
    )
    return {"suite": frozen, "revision_ids": revised, "agent_attempts_launched": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backend-pid", required=True, type=int)
    args = parser.parse_args()
    database = args.database.resolve()
    url, token = connection_for_process(args.backend_pid, database)
    fd, name = tempfile.mkstemp(
        prefix=database.name + ".t3-scope-", suffix=".bak", dir=database.parent
    )
    import os

    os.close(fd)
    with (
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source,
        sqlite3.connect(name) as target,
    ):
        source.backup(target)
    result = revise_t3_cases(
        Rpc(url, token),
        json.loads((ROOT / "evals/t3code/prompt-scope-v2.json").read_text()),
    )
    print(json.dumps({"backup": name, **result}, indent=2))


if __name__ == "__main__":
    main()
