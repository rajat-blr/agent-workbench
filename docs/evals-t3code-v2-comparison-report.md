# T3 v2 scope-explicit comparison

Status: completed on 2026-10-08. Experiment 3, **T3 v2 five-case comparison — medium vs high**. The paired verdict is **inconclusive**.

## Design

- Frozen suite v2, version ID 3, revisions 6–10. Only the prompts changed from v1: each explicitly names the single production file already enforced by its grader.
- Reused immutable configuration snapshots 2 (medium) and 3 (high), model alias `gpt-6.1-sol`. No configurations were recaptured. The only captured configuration difference is reasoning effort.
- Ten attempts, one per case/configuration, concurrency one, 600-second timeout each, no retries. Shell networking is disabled; baseline dependencies are installed offline. Held-out verifiers are installed after the agent diff is captured.
- A separately named experiment preserves original v1 results. The runner refuses duplicate experiment names, overlapping ready/running experiments, unexpected suite versions, invalid cases, and configurations outside the approved model/effort/sandbox settings.
- Runtime plan/result directory: `/private/tmp/uiagg-t3-comparison-9wtm5w0c`. Finished outcomes and integrity/cleanup evidence must be reviewed before interpreting the comparison.

## UI verification

On 2026-10-08 the user confirmed: **“Layouts and scrolling look correct”** in response to checking the main app's results/configuration layouts and trace scrolling. This is user verification, not an automated visual result.

Automation opened the saved v1 summary and failed-attempt evidence, exposed configuration cards, and observed experiment 3 appear automatically. Native scrolling returned `noWindowsAvailable`; screenshots subsequently remained stale. No claim is made that automation verified resizing or trace geometry.

## Results

| Case | Medium | High |
| --- | --- | --- |
| Trimmed IDs | Fail | Fail |
| Worker recovery | Fail | Fail |
| Cache pruning | Pass | Timeout |
| Concurrent settings | Pass | Pass |
| IndexedDB recovery | Pass | Pass |

Medium completed with three passes and two functional failures. High completed with two passes, two functional failures, and one timeout. All ten attempts are terminal; no retries were launched. Attempt IDs are 12–21, run IDs 17–26.

The UI's evaluable pass rates are 60% (3/5) for medium and 50% (2/4) for high. The high timeout is counted separately, not silently treated as a functional failure or included in that denominator. The cache pair is excluded from paired inference. The remaining four pairs comprise two both-pass and two both-fail cases, no discordant pairs, and exact McNemar p=1.0. This establishes neither superiority nor equivalence.

Both schema attempts stayed within the explicitly allowed file, resolving the v1 scope violations. High still failed the forward-compatible array invalid-element encoding assertion (102/103 tests passed). Medium also failed that assertion and generated-value round trips, with 32 failures reported, including exhausted property generators. Those generator failures warrant reviewing the produced schema's construction/annotations; they are not evidence of an agent infrastructure outage.

Both worker patches passed two of three assertions. Medium failed quiet shutdown during an item; high failed continuing after failed/defective items. Cache medium passed 11/11; both settings attempts passed 11/11; both IndexedDB attempts passed 10/10.

### Timeout and timing boundary

High cache reached the configured timeout before producing source changes. Its run error is `Codex exceeded the 600s run timeout`; no scorer result is available. No automatic rerun was performed.

The persisted agent duration is 50,473 ms, while run timestamps span 07:29:48.907469–07:40:57.356277 UTC (about 668 seconds). A subsequent [clock investigation](evals-timeout-investigation-2026-10-08.md) found overlapping host sleep and a mismatch between the scheduler's awake-only clock and the runtime's sleep-inclusive timeout clock. Future phase measurements now use the event-loop clock; original measurements and outcomes remain unchanged. Do not compare performance or attribute the timeout to reasoning effort from this batch. Repeating the affected pair requires separate approval.

### Integrity and history

All ten compressed raw trace checksums and sizes verified, with 353 parsed events. Reviewed 132 completed commands, including local-check code and file paths: no upstream solution fetches, held-out verifier reads, home-data reads, or other-repository reads were observed. Some commands searched for absent test paths and used focused temporary checks. This is trace review, not proof of hardened read isolation.

Every disposable worktree and registration was removed, attempt worktree pointers were cleared, and all five baselines remain clean at their pinned SHAs. All nine scored attempts passed their production-only diff checks. The timed-out attempt had no changed files and was not graded.

Existing records were compared against the pre-v2 backup: all three sessions, 17 messages, 16 prior runs, 647 prior events, five original revisions, three configuration snapshots, two original experiments, eleven old attempts, and their scores/suite memberships remain unchanged.

[Compact machine-readable evidence](evidence/t3code-v2-comparison-2026-10-08.json) includes outcomes, scorer failure lines/tails, configuration/preflight data, artifact checksums, cleanup checks, hashed command previews, the history audit, and timeout timestamps. Full result/audit files remain in the runtime directory above; raw traces and diffs remain in the app artifact store.

Five curated public-code cases do not support a broad configuration ranking. V1/v2 differences cannot be attributed solely to clearer prompts: these are single fresh stochastic attempts, and v2 includes a timeout. Model aliases, CLI installation, authentication, and instruction discovery remain observed rather than immutable environment pins.
