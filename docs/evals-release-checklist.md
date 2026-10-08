# Evals release checks

This is a verification record for the current source build, not a declaration that the full PRD is finished.

## Verified

- Backend regression suite: 111 tests passing, including migrations, retry history, hidden verifiers, immutable case revision cloning, setup/scorer cancellation, restart/resume, scope-overlay safety, event-loop phase timing, existing configuration reuse/duplicate guards, output artifacts, configuration capture, output limits, T3 packaging safety, and evidence checksum/path-escape checks.
- Scorer cancellation on POSIX reaps the parent and stops a descendant heartbeat process.
- Large stdout/stderr retain full evidence within the cap; output beyond 4 MiB per stream is unavailable/infrastructure failure.
- Frontend production and demo builds, lint, and two synthetic-demo fixture checks pass.
- Frozen backend builds with PyInstaller. Isolated startup applies migrations 1–8 and responds to authenticated health and Evals list RPCs.
- Electron Forge produces an unsigned macOS arm64 app bundle containing the production frontend and bundled backend. This is a packaging check, not interactive end-to-end validation.
- A real one-case experiment passed in the packaged UI using authenticated Codex CLI 0.159.3. Held-out assertions, source-only diff, token metrics, artifact checksum, and worktree cleanup were verified. See [the run report](evals-real-smoke-report.md).
- Five external T3 Code cases were packaged, scorer-verified, and published in both isolated and active UI databases; suite v1 is frozen. Each buggy baseline fails its held-out scorer, and each reference fix passes with a valid diff (138 tests total). All five Published/Valid cases were verified visibly in the running UI after refresh. Existing chat counts were preserved, and the active database was backed up. See [the suite record](evals-t3code-suite.md).
- A real T3 cache-pruning pilot passed all 11 held-out tests with an allowed single-file diff. Explicit model/reasoning settings, raw trace checksum, scope review, and worktree cleanup were verified. See [the pilot report](evals-t3code-pilot-report.md).
- The full T3 paired comparison completed ten attempts: medium passed 4/5, high 3/5, with no infrastructure errors or retries. The paired verdict is inconclusive. All raw trace checksums and worktree cleanup checks passed; schema scope violations and functional failures are retained. Evals now periodically discovers API-created records; that refresh and final result-screen visual verification remain unverified interactively. See [the comparison report](evals-t3code-comparison-report.md).
- Synthetic Evals demo exposes a completed comparison, filters, configuration diff, and attempt evidence without a backend. Mutating RPCs are rejected.
- Updated packaged backend passed synthetic cancellation, hard-restart reconciliation, explicit resume, and two-turn chat checks on copied data. UI start/cancel and historical comparison summaries passed accessibility checks. Five scope-explicit T3 revisions validated and froze as v2 in that copy only; active v1 and historical results were preserved. See [the verification record](evals-release-verification-2026-10-07.md).
- Subsequently, the idle main source app was restarted and scope-explicit T3 v2 was published in its active database after backup. All five cases are Published/Valid, suite v2 is frozen, and a row-level audit confirms old chats and evaluation history are unchanged. No new model runs were launched. Main-app visual verification remains pending due to native UI control failures. See [live publication evidence](evidence/t3code-live-v2-2026-10-07.json).
- On 2026-10-08 the user confirmed results/configuration layouts and trace scrolling look correct. Automation verified opening views and automatic discovery of the v2 experiment, but scrolling/screenshot limitations remained; resizing is not independently verified.
- V2 completed ten real attempts using the unchanged v1 snapshots: medium three passes/two failures; high two passes/two failures/one timeout. All ten raw trace checksums and cleanup checks passed; nine graded diffs stayed within scope, and the timed-out attempt had no changes. Historical rows remain unchanged. The four evaluable pairs are inconclusive. See [v2 report](evals-t3code-v2-comparison-report.md).

## Still required before release sign-off

- Complete interactive restart/resume and real chat thread-resume checks; packaged API lifecycle checks and UI cancellation are covered above.
- Complete supported-window-size/resizing checks. Main results/configuration layouts and trace scrolling were user-confirmed above.
- Replace or supplement the explicitly synthetic Evals demo with an approved real recording.
- Confirm release artifact versioning, signing/notarization policy, and final release notes.

## Known boundaries

- Instruction snapshots and detected CLI versions are observed, not pinned; custom fallback instruction names and external authentication remain uncontrolled.
- Redaction recognizes credential patterns, not every possible secret. Never place secrets in instruction content.
- Repeated-sample comparisons remain descriptive/inconclusive until case-level uncertainty is implemented.
- Commands retain at most 4 MiB per stream in memory. Beyond that limit they are terminated; unbounded disk streaming is not implemented.
- Hard-crash reconciliation does not guarantee orphan-agent termination: the packaged crash fixture manually reaped its captured agent group.
- Screenshot capture was stale and then failed with ScreenCaptureKit `-3811`; accessibility checks do not constitute visual layout sign-off.
- V2's cache timeout overlapped host sleep; scheduler duration and runtime timeout used clocks with different sleep semantics. Future phase durations now use the event-loop clock, with deterministic regression coverage; historical results are unchanged. This correction requires backend restart/rebuild and has not been verified with a live suspend. Do not use this batch for performance comparisons or infer a reasoning-effort effect on timeout. See [investigation](evals-timeout-investigation-2026-10-08.md).
