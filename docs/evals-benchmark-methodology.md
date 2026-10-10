# Benchmark methodology

## Authoring and validation

Create cases in the Evals UI, configure their baseline, prompt, setup, held-out verifier and allowed changes, then validate and publish them. Assemble published case revisions into a frozen suite before comparing configurations. The demo bundles a read-only [four-case portfolio recording](evals-portfolio-comparison.md), not an executable upstream benchmark pack. Its public history has an unverified training cutoff.

Optional `backend/tools/mine_eval_cases.py` discovers single-parent commits touching tests and production source. It exports history-free parent baselines without affected test files, preserving upstream-tracked files even when ignore rules match them. Verifiers and production-only reference patches remain separate from agent inputs. Discovery does not execute repository code or establish a regression.

Opt-in validation uses operator-supplied setup and test argument arrays. It requires repeated functional baseline failures followed by repeated reference successes with identical tests. Setup errors, already-passing baselines, reference failures, unexpected changes and verifier modifications reject a draft. Match the baseline's package manager, pin tooling, use frozen dependencies and do not update snapshots to obtain passes. Review behavioral prompts, grading scope and related fixes before publication.

`backend/tools/audit_mined_inventory.py` verifies evidence hashes, repeated validation scores and baseline isolation, deduplicates cases by source/commit, and flags shared production paths for review. It never imports, publishes or starts agents. Local audit success does not replace app validation or establish task independence.

## Case-level inference

The analysis unit is the frozen case revision. Retry deduplication takes the latest attempt for each case/configuration/sample. Each configuration's primary pass rate is the equal-weight mean of evaluable per-case pass rates; pooled attempt pass rates are descriptive only.

Paired inference matches evaluable sample indices, calculates a mean configuration difference within each case, and applies a two-sided exact sign test across non-tied case differences. Repetitions do not increase the inferential case count. At least six non-tied cases are necessary to reach p < 0.05 with this test. Deterministic 4,096-resample percentile bootstraps resample cases for the mean pass rate and paired mean difference; fewer than two cases produce no interval. Uniform outcomes can produce collapsed intervals, which are not significance evidence.

Missing, cancelled and infrastructure observations are excluded explicitly; conclusions are conditional on matched evaluable observations. Related commits may remain correlated. Review overlapping fixes and report this limitation: the current case-level analysis does not automatically account for cross-case clustering.

## Sensitivity and run budgets

`backend/tools/positive_control.py` prepares a normal configuration versus deliberately no-edit instructions. Planning is dry-run-first; applying the plan does not start agents. Freeze the suite and declare the model, sample count and run budget before execution. Passing a sensitivity control requires measured results, not merely a configured control.

Thirty cases × two configurations × three samples means 180 attempts per experiment. Repeated samples are not additional independent cases. Do not make comparative performance claims before auditing completed evidence.

## Contamination and isolation limits

Public history may be present in model training. Record source visibility, exact revisions and the basis for any training-cutoff claim; recent Git timestamps alone do not prove fixes were unseen. The miner's training-cutoff filter is an operator declaration, not independent verification. Private-source declarations also do not establish training exclusion.

History-free baselines remove local reference history but do not erase model knowledge. Offline policy prevents intended network use; sibling verifier files and source clones are not an OS security boundary. Never place credentials in fixtures, prompts or instruction snapshots.
