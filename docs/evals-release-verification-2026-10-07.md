# Packaged Evals verification — 2026-10-07

These are synthetic lifecycle checks against the production frontend and frozen backend, not new model-quality results. The existing ten-attempt T3 comparison remains unchanged.

## Changes

- Published cases now expose **New draft revision**. The editor includes the task prompt. Prompt-only saves preserve all existing scorers, setup, path policies, and held-out verifier inputs. Verifier bundles are copied to revision-owned storage; old revisions and frozen suites remain immutable.
- Experiment cancellation now interrupts setup and scoring tasks as well as agent processes, waits for cleanup, and cancels queued attempts without launching them. Agent startup is shielded until process registration completes so cancellation cannot strand a just-started process.
- A checked, idempotent T3 scope overlay explicitly names the same single production file already enforced by each diff grader. It creates new revisions and a new frozen suite, without rerunning agents.
- A disposable Electron profile option and packaged-check harness support testing copied data without restarting the working app.

## Results

- Backend: **107 tests passed**. Ruff passed. Frontend production build, lint, and both demo fixture tests passed.
- PyInstaller rebuilt the backend. A separately named, unsigned macOS arm64 QA app bundled that executable and the current frontend.
- In a consistent temporary database/artifact copy, all five T3 v2 revisions validated, published, and entered frozen suite v2. No model attempts were launched for this operation.
- Packaged API cancellation: running and queued attempts became cancelled, only one agent was launched, its parent process was reaped, and its worktree was removed. Automated setup/scorer cancellation tests additionally checked descendant heartbeats stopped.
- Hard backend termination: startup retained an interrupted attempt with `backend_restart`, retained queued work, and cleaned the abandoned worktree. Explicit resume completed the queued sample and a new retry while preserving the original infrastructure error.
- Two synthetic chat turns completed in one session and appeared in the packaged chat view. This does not independently verify the real CLI's thread-resume behavior.
- UI-driven start/cancel reached Running and then Cancelled in accessibility state; persisted outcomes confirm both attempts cancelled and no queued launch. Opening the historical T3 comparison exposed the correct 80%/60% summaries, ten attempts, and inconclusive verdict.
- Source database still has five original revisions and only the two original completed experiments. All five baseline repositories remain clean. The QA app and backend were stopped; temporary evidence was retained.

Compact evidence: [packaged lifecycle JSON](evidence/packaged-lifecycle-2026-10-07.json). Full disposable check output: `/private/tmp/uiagg-packaged-check-96r8c2jf/result.json`.

## Boundaries and next steps

The hard-crash test manually killed only its captured synthetic agent process group after killing its own backend. Automatic orphan termination after a hard crash is **not implemented or verified by this check**. Do not infer it from successful restart reconciliation.

Native UI screenshots remained stale relative to accessibility state and subsequently failed with ScreenCaptureKit error `-3811`. Result geometry, configuration layout, resizing, and long-trace scrolling still require reliable visual verification. Accessibility checks are not layout sign-off.

T3 v2 exists only in the disposable QA database. To publish it in the working database, first restart with the updated backend, then run `backend/tools/revise_t3_prompts.py` with that database path and the exact backend PID. The tool verifies the connection and takes a consistent backup before updating. Historical v1 inputs and results must remain intact.

Remaining release work includes reliable visual checks, an approved real demo recording, and release version/signing/notarization decisions.
