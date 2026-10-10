# Recorded Zod + Hono comparison

Completed 2026-10-10 (Asia/Kolkata), in the source app. Four published cases, two configurations, one sample per case/configuration: **eight real attempts, no retries**. Model: `gpt-6.1-sol`; only reasoning effort differs between snapshots. Same safety preamble, offline workspace-write policy, 600-second attempt timeout, concurrency one.

| Configuration | Held-out + source-only passes | Median agent duration | Output tokens, total |
| --- | --- | --- | --- |
| Low reasoning | 4/4 | 60.5s | 7,528 |
| High reasoning | 4/4 | 102.1s | 15,607 |

Durations exclude setup and scoring. No infrastructure failures. **Inconclusive:** four tied cases cannot establish a configuration ranking. Timing is descriptive for this run, not a general speed claim. Uniform case-bootstrap intervals collapse here and do not establish certainty. No positive-control experiment was run.

## Cases and evidence

| Source | Task | Reference commit |
| --- | --- | --- |
| Zod | Exclude numeric enum reverse names from options | `90269c601aae25499ee87e78a07508564825867f` |
| Zod | Preserve narrower integer bounds | `7a00236683c79000dbab0d92f6faf0b7fba39f59` |
| Hono | Preserve empty query parameters | `28e8572cd265b4da1160ce6cd51919bb70516e2c` |
| Hono | Safely handle invalid/bodyless pretty-JSON responses | `f950277cd3d9264622785e82785f21c648da699a` |

Held-out tests failed twice on each parent baseline and passed twice after the reference patch; cases also passed app validation before publication. Agent baselines omit affected tests and reference history. Required graders check held-out regression tests and production-only changes. All eight saved raw-event artifact checksums were verified before export.

The [recording](../frontend/src/data/portfolioBenchmark.json) contains actual API payloads, responses, diffs, grader logs, events, normalized steps, source parents and evidence hashes. Machine-local paths and recognized credential patterns are redacted. Original chat records were preserved. Upstream code retains its [MIT attribution](../evals/THIRD_PARTY_LICENSES.md).

These are public repositories: model training cutoff and contamination are unverified. History-free checkouts do not erase prior model knowledge. Four selected cases are not broad repository coverage or proof of harness sensitivity.

## Screenshot walkthrough

Main app: **Evals lab → Evaluations → Zod + Hono → Open results**. Refresh the dev renderer if stale. Click **Compare outputs** beside a case, then inspect **Responses**, **Code changes**, **Scorer results** and **Execution traces**. **Configurations** shows the reasoning-only difference. All attempts passed; the failure filter honestly shows no matching cases.

Browser demo: `npm --prefix frontend run build:demo`, then `npm --prefix frontend run preview`. It opens recorded Evals results automatically and needs no backend or model calls. Chat examples remain synthetic; Evals mutations are disabled. Rebuild normally before packaging production. No updated desktop installer or hosted deployment is implied.
