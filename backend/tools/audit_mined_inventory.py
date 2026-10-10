"""Audit and deduplicate validated draft reports; never publish or start agents."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.eval_baselines import audit_baseline


def inventory(sources: list[tuple[str, Path]]) -> dict:
    cases = {}
    reports = []
    for source, report_path in sources:
        report_path = report_path.resolve()
        root = report_path.parent
        report = json.loads(report_path.read_text())
        if report.get("mode") != "validated_drafts":
            raise ValueError("Discovery reports are not validated case evidence")
        if report["accepted_count"] != len(report["cases"]):
            raise ValueError("Report count does not match its cases")
        reports.append({"source": source, "path": str(report_path)})
        for item in report["cases"]:
            if item["status"] != "validated_draft":
                raise ValueError("Expected a validated draft")
            baseline = Path(item["baseline"]).resolve()
            private = Path(item["private"]).resolve()
            if not baseline.is_relative_to(root) or not private.is_relative_to(root):
                raise ValueError("Case paths must remain within the report directory")
            for filename in ("scores.json", "import.json"):
                if not (private / filename).resolve().is_relative_to(private):
                    raise ValueError("Evidence file escapes the private directory")
            audit_baseline(baseline, set(item["test_paths"]), item["base_sha"])
            for filename, field in (
                ("verifier.json", "verifier_sha256"),
                ("reference.patch", "reference_patch_sha256"),
            ):
                path = private / filename
                if not path.resolve().is_relative_to(private):
                    raise ValueError("Evidence file escapes the private directory")
                if hashlib.sha256(path.read_bytes()).hexdigest() != item[field]:
                    raise ValueError("Evidence checksum mismatch")
            scores = json.loads((private / "scores.json").read_text())
            repetitions = item["validation_repetitions"]
            if repetitions < 2:
                raise ValueError("Inventory requires two validation repetitions")
            for stage, expected_status, expected_exit in (
                ("baseline", "fail", 1),
                ("reference", "pass", 0),
            ):
                rows = [row for row in scores if row["stage"] == stage]
                if len(rows) != repetitions or any(
                    row["status"] != expected_status
                    or row["value"].get("exit_code") != expected_exit
                    for row in rows
                ):
                    raise ValueError("Incomplete or inconsistent validation evidence")
            if any(
                row["status"] != "pass" for row in scores if row["stage"] == "setup"
            ):
                raise ValueError("Setup evidence must pass")
            key = (source, item["commit"])
            entry = {
                "source": source,
                "commit": item["commit"],
                "parent": item["parent"],
                "production_paths": item["production_paths"],
                "test_paths": item["test_paths"],
                "verifier_sha256": item["verifier_sha256"],
                "reference_patch_sha256": item["reference_patch_sha256"],
                "validation_repetitions": repetitions,
                "import_payload": item["import_payload"],
                "review_status": "prompt_scope_and_independence_review_pending",
            }
            if key in cases and any(
                cases[key][field] != entry[field]
                for field in ("verifier_sha256", "reference_patch_sha256", "parent")
            ):
                raise ValueError("Duplicate commit has conflicting evidence")
            cases.setdefault(key, entry)
    overlaps = {}
    for entry in cases.values():
        for path in entry["production_paths"]:
            overlaps.setdefault((entry["source"], path), []).append(entry["commit"])
    return {
        "schema_version": 1,
        "status": "audited_validated_drafts_not_published",
        "case_count": len(cases),
        "counts_by_source": {
            name: sum(key[0] == name for key in cases)
            for name in sorted({name for name, _ in sources})
        },
        "reports": reports,
        "cases": sorted(cases.values(), key=lambda row: (row["source"], row["commit"])),
        "overlap_review_groups": [
            {"source": source, "path": path, "commits": sorted(commits)}
            for (source, path), commits in sorted(overlaps.items())
            if len(commits) > 1
        ],
        "model_attempts": 0,
        "warning": "Audit checks local evidence integrity, not independence, prompt quality or contamination.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", action="append", required=True, help="NAME=report.json; repeatable"
    )
    parser.add_argument(
        "--output", type=Path, help="Optional new JSON file; never overwrites"
    )
    parser.add_argument(
        "--portable",
        action="store_true",
        help="Omit machine-local import/report paths from the exported catalog",
    )
    args = parser.parse_args()
    sources = []
    for value in args.source:
        name, separator, path = value.partition("=")
        if not name or not separator or not path:
            parser.error("Sources must have NAME=report.json form")
        sources.append((name, Path(path)))
    result = inventory(sources)
    if args.portable:
        result["reports"] = [
            {"source": row["source"], "directory": Path(row["path"]).parent.name}
            for row in result["reports"]
        ]
        result["cases"] = [
            {key: value for key, value in row.items() if key != "import_payload"}
            for row in result["cases"]
        ]
    if args.output:
        with args.output.open("x") as output:
            json.dump(result, output, indent=2)
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}))


if __name__ == "__main__":
    main()
