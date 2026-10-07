# T3 Code five-case reasoning comparison

Outcome: completed. Medium passed 4/5 cases; high passed 3/5. The paired
comparison is **inconclusive**, not evidence of a reliable configuration winner.

## Run design

- Date: 2026-10-06; active database `backend/agent_workbench.db`.
- Experiment 2: **T3 five-case comparison — medium vs high**.
- Frozen five-case suite version 1; config snapshots 2 (medium) and 3 (high).
- Model alias `gpt-6.1-sol`; observed Codex CLI `0.159.3`.
- One fresh attempt per case/configuration: ten attempts total, concurrency 1,
  600-second agent timeout each; no automatic retries.
- Both configurations use identical generalized scope instructions. The pilot
  preamble named the cache file specifically and could not safely be reused for
  the other cases. This comparison is not a rerun of the exact pilot snapshot.
- Configuration diff verified that only `reasoning_effort` differs. Both arms
  use workspace-write with shell networking disabled, ephemeral execution,
  ignored user config, offline frozen dependency setup, and post-agent hidden
  verifier installation in disposable Git worktrees.

The OpenAI Docs skill informed verification of the reasoning configuration
control against [official developer settings](https://learn.chatgpt.com/docs/developer-settings).
No new credentials or authentication settings were created. Model alias,
installed CLI, repository instruction discovery, and existing authentication
are recorded/observed, not immutable model or environment pins.

## Results

| Case | Medium | High | Held-out assertions (medium / high) |
| --- | --- | --- | --- |
| Trimmed IDs | Fail | Fail | 102/103 / 102/103 |
| Worker recovery | Pass | Fail | 3/3 / 2/3 |
| Cache pruning | Pass | Pass | 11/11 / 11/11 |
| Concurrent settings | Pass | Pass | 11/11 / 11/11 |
| IndexedDB recovery | Pass | Pass | 10/10 / 10/10 |

All ten attempts completed with no infrastructure errors, timeouts, cancellations,
or retries. Attempt IDs 2–11, eval run IDs 7–16. Medium's 80% pass rate has a
95% Wilson interval of 37.6–96.4%; high's 60% has 23.1–88.2%. Three pairs both
passed, one pair both failed, and worker recovery was the single discordant pair
(medium only). Exact paired McNemar p-value: 1.0. These five observations do not
establish superiority or equivalence.

### Failures worth reviewing

Both schema patches rejected whitespace correctly but broke forward-compatible
array encoding: an invalid element threw instead of encoding as a hole. Both
also changed `packages/contracts/src/t3ProjectFile.ts`, violating the grader's
single-file allowance. The prompt said to limit changes to contracts, rather
than explicitly naming the allowed file. Clarify that scope in a future case
revision; do not silently change this frozen experiment's grading. Both attempts
independently failed a functional assertion, so their failures are not solely
caused by the scope mismatch.

The high worker patch stayed within scope but failed the recovery assertion:
the later `ok` item was not processed after preceding failures/cancellation.
Its own scratch checks had passed; the held-out regression exposed the gap.

### Observed usage

| Metric, across five attempts | Medium | High |
| --- | ---: | ---: |
| Median agent duration | 113.850 s | 130.649 s |
| Input tokens, including cached | 2,455,448 | 2,390,245 |
| Cached input tokens | 2,243,200 | 2,158,336 |
| Output tokens | 16,610 | 24,167 |
| Reasoning output tokens | 2,654 | 6,954 |

These are descriptive CLI counters, not billing measurements or an estimate of
configuration cost. Fixed run order and cache/environment effects limit timing
comparisons.

### Integrity and cleanup

All ten compressed raw trace checksums and sizes matched; gzip decompression
and parsing succeeded for 384 events. Reviewed 143 completed shell commands:
no upstream fetch/search, other-repository reads, evaluation-artifact reads, or
home user-data reads were observed. Some commands looked for absent held-out
test paths; those files were not in the agent baselines. This is trace review,
not a hardened read-isolation proof.

Every attempt's disposable worktree was removed, its worktree pointer cleared,
and its Git worktree registration removed. All five source baselines remain
clean at their pinned commits. Eight diffs stayed within the allowed source
file; the two schema diffs were rejected as described above.

[Machine-readable evidence](evidence/t3code-comparison-2026-10-06.json) retains
attempt outcomes, scorer evidence tails, metrics, configuration metadata,
checksums, cleanup checks, and hashed command previews. Full traces, diffs,
snapshots, and scorer output remain in the active app database/artifact store.
The complete runtime result and audit are in
`/private/tmp/uiagg-t3-comparison-7e8k273h`.

Results are saved under **Evals → Experiments → T3 five-case comparison — medium
vs high**. Final visual result verification is still incomplete.

## Interpretation boundaries

Five curated public-code cases provide scenario evidence, not a representative
benchmark or a strong statistical ranking. Public upstream fixes may be present
in training data. Hidden verifier files are absent from baseline Git history
and installed after execution, but this is not an adversarial filesystem-read
boundary. Trace review can identify observed violations, not prove secrecy.
Run order is fixed and sequential, not randomized; token counters are reported
CLI usage, not billing. Cases have different test counts: do not pool individual
assertions as independent samples for comparing configurations.

Native UI screenshots and accessibility state were inconsistent during this
run. Persisted API results must not be described as visually verified results.

## Implementation verification

Added bounded suite launch guards and a read-only trace/checksum/cleanup auditor.
Also corrected Evals discovery of API-created records: visible live Evals now
refreshes cases, suites, configurations, and experiments every ten seconds and
on window focus; its existing subscriptions continue providing detailed progress.
The synthetic demo is not periodically polled. Backend regression tests: 97
passing; backend and frontend lint, frontend production build, and both demo
fixture tests pass. Audit tests cover checksum tampering and artifact path
escape rejection. The refresh change has not been interactively verified.

## Next

Clarify file-scope constraints in future case prompts and review the failed
schema/worker patches before expanding the benchmark. Release verification
still needs interactive result-layout checks and packaged-app cancellation,
restart/resume, and chat-regression checks. No additional agent attempts were
launched automatically after this comparison.
