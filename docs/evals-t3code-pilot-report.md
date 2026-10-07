# T3 Code real agent pilot

Outcome: pass. One cache-pruning case, one configuration, one attempt.
This is a smoke pilot, not a full-suite comparison or statistical performance claim.

## Run identity

- Date: 2026-10-06.
- Active app database: `backend/agent_workbench.db`.
- Experiment 1: **T3 cache-pruning pilot**; completed.
- Case/revision 3, config/snapshot 1, attempt 1, eval run 6.
- Separate one-case frozen suite 2/version 1. Original five-case suite 1/version 1 unchanged.
- Baseline: `.eval-cases/t3code/cache-pruning`, commit
  `321800cfb55362ef6a371c63b324b0322b30dd07`.

## Configuration and limits

Used the model already configured locally, explicitly recorded as `gpt-6.1-sol`,
with medium reasoning. Codex CLI observed version: `0.159.3`. Model alias, reasoning,
workspace-write sandbox, and network-disabled shell policy were supplied for this
attempt. The runner used ephemeral execution and ignored user `config.toml`.
The explicit preamble prohibited out-of-scope reads, upstream solutions, delegation,
live services, and persistent changes outside the allowed production file.

The OpenAI Docs skill informed checking the CLI flags before running the pilot;
the [official command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
documents model override, JSON output, ephemeral execution, ignoring user configuration,
and workspace-write options. Local `codex exec --help` confirmed those flags for
the installed version. Existing CLI authentication was used; no new credentials
were generated or changed.

One attempt, concurrency 1, 600-second agent timeout. Setup/scoring have their
own bounded command timeouts. No retry or full-suite launch was performed.
CLI version, instruction discovery, authentication, and underlying model revision
remain observed inputs; the model alias is explicit, not an immutable model build.

## Verified result

- Held-out scorer: exit 0, **11 tests passed**. It was installed only after the
  agent finished, through the app verifier bundle handler.
- Required diff scorer: pass. Only
  `apps/server/src/pullRequest/PullRequestReadCache.ts` changed: +8 / −5 lines.
- The patch limits pruning to exact-length lowercase hexadecimal cache entry
  names and checks that the candidate is a regular file before deleting it.
  It also updates the associated explanatory comment.
- The agent performed local filesystem scratch checks and formatting/diff checks.
  Some exploratory commands failed, including an unsupported lint invocation;
  those are trace events, not held-out scorer failures.
- All ten completed shell commands were reviewed. No upstream searches/fetches,
  other-repository reads, evaluation-artifact reads, or home-user-data reads were
  observed. This is trace review, not a hardened filesystem-read boundary.
- Compressed raw JSONL artifact 6: 26,620 bytes, 28 raw events; SHA-256
  `e2eee9085d084a79fd8118bdb19a392eb6f8cb6e0f6538d131c12db6110c8e16`
  matched stored bytes. Gzip decompression and JSONL parsing succeeded.
- Disposable worktree removed, attempt worktree pointer cleared, Git worktree
  registration removed, and source baseline remains clean at its pinned commit.
- Backend lint and all **87 tests** pass, including guards against silently
  rerunning an existing pilot or starting more than one/network-enabled attempt.

## Observed timings and tokens

| Metric | Value |
| --- | ---: |
| Setup | 12.252 s |
| Agent | 108.146 s |
| Scoring | 1.389 s |
| Input tokens, including cached | 382,359 |
| Cached input tokens | 342,400 |
| Output tokens | 3,868 |
| Reasoning output tokens | 642 |

These are CLI-reported usage counters, not measured billing or a cost estimate.
The app correctly reports the comparison verdict as inconclusive: only one
configuration and one case were measured.

## Evidence and next step

[Machine-readable evidence](evidence/t3code-pilot-2026-10-06.json) includes the
attempt/scorer payloads, captured diff, preflight warnings, metrics, and audit.
The result is persisted in the active app under **Evals → Experiments → T3
cache-pruning pilot**. Final visual verification of its result screen was not
completed because native UI actions and observations became inconsistent; the
completed result was verified through the app API and database instead.

Follow-up completed: the [five-case paired comparison](evals-t3code-comparison-report.md)
used matching generalized scope instructions (the pilot's cache-specific guard
could not be reused unchanged). Medium passed 4/5 and high 3/5; verdict
inconclusive. The comparison does not reuse this pilot attempt as a sample.
