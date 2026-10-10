# Evals release checks

This is a verification record for the current source build, not a declaration that the full PRD is finished.

## Verified

- Results UI includes case-weighted score and median execution-time charts, a case/configuration grid, failure filtering, and side-by-side responses, patches, scorer evidence and trace timelines. Eleven recorded-demo/review tests, production/demo builds, lint and typed-contract checks pass. Browser checks verified the real recording's comparison tabs, failure filter and reasoning-only snapshot diff. The main dev app visibly lists the completed experiment; no rebuilt installer is claimed.
- A four-case Zod + Hono comparison completed eight real attempts with no retries: low and high reasoning each passed 4/4. Eight raw-event artifact checksums were verified before exporting the read-only demo recording. Original chat sessions, messages and runs are unchanged; all attempt worktree paths were cleared. Backend tests: 191 passed. See [measured results and limits](evals-portfolio-comparison.md).
- The history miner preserves upstream-tracked ignored manifests; regression tests cover detached baseline checkout, repeated validation and evidence auditing. Repository-specific benchmark fixtures are not bundled. Create benchmarks through the Evals UI; see [methodology](evals-benchmark-methodology.md).
- Workspace/session catalogs use bounded ID-cursor pages; the UI loads beyond 500 sessions and retains presentation ordering. Seven backend and six frontend pagination tests pass, alongside all 39 frontend/Electron regression tests, contract/build/lint checks, backend formatting and generated-contract drift checks. No real database changes, interactive pagination QA or rebuilt installer for this batch. See [pagination behavior and limits](catalog-pagination.md).
- Safer Git source UI includes unchecked per-file selection, staged-file commit review, and configurable remote/destination pushes. Thirteen backend Git tests and three frontend selection tests pass; real workspace mutations and full interactive dialog QA were not performed. See [Git safeguards](git-actions-safety.md).
- Frontend chat synchronization and WebSocket transport pass eighteen deterministic regression tests, with hook dependency linting enabled. Live/history merging and stale-session guards are verified without real model calls; interactive chat race QA remains pending. See [coverage and limits](frontend-chat-sync.md).
- All 59 public RPC methods now share generated frontend input/result types and backend response validation. Twelve contract tests, compile-time invalid-call assertions and local generated-type drift checks pass. See [contract boundaries](rpc-contract.md).
- Core and Evals dispatch chains are replaced by registered domain handlers. Ten registry tests and a one-time AST comparison cover all 59 routes; existing integration regressions pass. See [handler refactor](rpc-handlers.md).
- Refactored backend freshly builds with PyInstaller and passes authenticated core/Evals startup smoke checks on a disposable database, with agent execution disabled. The production Electron smoke also passes; no new installer or real model experiment was produced in this batch.
- Explicit Ruff lint/format policy, readable exception syntax, backend metadata/lockfile rename, and narrowed PRD document ignores pass fourteen new regression tests. Flagged production async filesystem checks are offloaded; operator RPC tooling blocks non-loopback URLs, redirects, and ambient proxies. See [repository policy](lint-repository-policy.md).
- Source Electron hardening passes ten unit tests and a local hidden production-renderer smoke test: restricted protocol/CSP, trusted IPC, exact loopback HTTP/WebSocket access, blocked remote connections/inline scripts, and external-link routing. A rebuilt installer remains unverified. See [hardening checks](electron-hardening.md).
- Scorer cancellation on POSIX reaps the parent and stops a descendant heartbeat process.
- Large stdout/stderr retain full evidence within the cap; output beyond 4 MiB per stream is unavailable/infrastructure failure.
- Frontend production/demo builds, lint and typed-contract checks pass, alongside 56 frontend/Electron regression tests.
- Frozen backend builds with PyInstaller. Isolated startup applies migrations 1–8 and responds to authenticated health and Evals list RPCs.
- Electron Forge produces an unsigned macOS arm64 app bundle containing the production frontend and bundled backend. This is a packaging check, not interactive end-to-end validation.
- A real one-case experiment passed in the packaged UI using authenticated Codex CLI 0.159.3. Held-out assertions, source-only diff, token metrics, artifact checksum, and worktree cleanup were verified. See [the run report](evals-real-smoke-report.md).
- Recorded Evals demo exposes the real completed comparison, filters, configuration diff and attempt evidence without a backend. Mutating RPCs are rejected; chat examples remain synthetic.
- On 2026-10-08 the user confirmed results/configuration layouts and trace scrolling look correct. Automation verified opening views and automatic discovery of the v2 experiment, but scrolling/screenshot limitations remained; resizing is not independently verified.

## Still required before release sign-off

- Complete interactive restart/resume and real chat thread-resume checks; packaged API lifecycle checks and UI cancellation are covered above.
- Complete supported-window-size/resizing checks. Main results/configuration layouts and trace scrolling were user-confirmed above.
- Confirm release artifact versioning, signing/notarization policy, and final release notes.

## Known boundaries

- Instruction snapshots and detected CLI versions are observed, not pinned; custom fallback instruction names and external authentication remain uncontrolled.
- Redaction recognizes credential patterns, not every possible secret. Never place secrets in instruction content.
- Case-level pass rates, case-resampled intervals and an exact paired case sign test are implemented. The recorded comparison remains inconclusive; sensitivity validation and broader performance claims require additional approved runs. See [methodology](evals-benchmark-methodology.md). Repeated attempts do not constitute independent cases.
- Commands retain at most 4 MiB per stream in memory. Beyond that limit they are terminated; unbounded disk streaming is not implemented.
- Hard-crash reconciliation does not guarantee orphan-agent termination: the packaged crash fixture manually reaped its captured agent group.
- Screenshot capture was stale and then failed with ScreenCaptureKit `-3811`; accessibility checks do not constitute visual layout sign-off.
- Scheduler phase durations now use the event-loop clock with deterministic regression coverage. Live suspend behavior remains unverified; do not infer runtime-performance effects from these checks.
