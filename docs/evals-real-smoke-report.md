# Real packaged-app evaluation — 2026-10-05

Result: **PASS**, one real Codex attempt. This validates the execution/evidence pipeline, not model superiority.

## Execution

- Packaged macOS arm64 Agent Workbench app; installed `codex-cli 0.159.3`, using existing ChatGPT authentication.
- Started through the Evals lab UI; completed results, scorer evidence, normalized steps, and saved diff inspected in the packaged UI.
- One published case, one frozen suite, one immutable configuration, one sample, no retries. Medium reasoning, restricted workspace-write sandbox, agent-tool network disabled, 180-second timeout.
- Model selection used the CLI default; the effective model was not recorded/pinned. Instruction snapshots and authentication remained observed inputs.
- CLI execution uses the non-interactive JSON event stream described in the [official OpenAI documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

## Task and evidence

Fix `normalize_label(value)` to trim/collapse whitespace, lowercase text, preserve Unicode, and return an empty string for blank input. The isolated fixture baseline was `3798ba2323c19e766d0ae04ec0ac0112d4d28a15`.

The held-out verifier was absent during the agent run and installed for validation/scoring. Baseline validation failed as expected. Final scoring passed all seven assertions covering spaces, tabs/newlines, empty/blank input, Unicode, and already-normalized input. The source-only diff constraint also passed.

```diff
-    return value.lower()
+    return " ".join(value.split()).lower()
```

Only `labels.py` changed: one insertion, one deletion. The original fixture checkout remains unchanged and clean. The disposable attempt worktree was removed. The saved raw JSONL artifact checksum was verified.

## Measurements

- Agent duration: 32,269 ms; scoring: 55 ms; setup: 0 ms at millisecond resolution.
- Input tokens: 46,453, including 42,496 cached input tokens; output tokens: 433; reported reasoning output tokens: 0. Cached input is a subset, not additional input.
- Outcome: 1 pass, 0 fail, 0 infrastructure errors. Wilson 95% interval: approximately 20.7%–100%; a single sample does not establish a reliable general pass rate.
- Comparison verdict: inconclusive / no paired comparison, because only one configuration was tested.

## Local data and limitations

The app is using an isolated test database, not the normal desktop conversation database:

`/private/tmp/uiagg-real-eval.d3NWbk/experiment.db`

Artifacts and the untouched fixture are in the same temporary directory. Temporary data may eventually be cleaned by the operating system. The durable [evidence summary](evidence/real-eval-smoke-2026-10-05.json) preserves results, scoring evidence, measurements, and the diff without copying authentication or global instruction content.

Not validated by this run: cancellation/restart mid-execution, a two-configuration comparison, large traces in the UI, or fresh-machine installation. This real fixture has no third-party dependencies; its verifier invokes the development Python interpreter explicitly.
