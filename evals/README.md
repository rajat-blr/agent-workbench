# Evaluation benchmarks

The portfolio demo replays a real four-case Zod + Hono comparison: eight attempts, low versus high reasoning, both 4/4 passes. It includes responses, patches, scorer evidence and traces, without running agents. See the [run report](../docs/evals-portfolio-comparison.md), [recording](../frontend/src/data/portfolioBenchmark.json) and [upstream licenses](THIRD_PARTY_LICENSES.md). This is a small workflow showcase, not a performance ranking or a portable executable benchmark pack.

Create and manage additional benchmarks directly in the application's Evals UI. The backend implementation lives in `backend/evals`.

The history miner in `backend/tools/mine_eval_cases.py` discovers test-and-production commits and optionally validates parent-fail/reference-pass behavior. Generated candidates, baseline repositories and held-out bundles live in ignored local directories. They are drafts: prompt quality, task independence and grading scope must be reviewed before publishing them in the app.

See [benchmark methodology](../docs/evals-benchmark-methodology.md) for case-level inference, the candidate sensitivity control and limitations. Discovery is not a completed benchmark or evidence of model performance.

Optional repository-agnostic helpers remain available for history mining and evidence auditing. They do not import, publish or run cases automatically.
