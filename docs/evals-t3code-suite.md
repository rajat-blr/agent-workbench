# T3 Code realistic evaluation candidates

Status: five cases packaged, scorer-verified, published, and frozen as suite v1
in both the isolated test database and the active UI database. All five are
visibly listed in Evals → Cases as Published and Valid. A real one-case T3 pilot
has now passed all 11 held-out tests; the five-case agent run/comparison remains.
See [the pilot report](evals-t3code-pilot-report.md).

## Source and isolation

Use [T3 Code](https://github.com/pingdotgg/t3code), pinned to
`8f75697b9e022033f2615cb32e3c6ddc61c52353`, independently of UIagg.
The source clone is in ignored `.eval-sources/t3code`; validation used a
separate ignored `.eval-validation/t3code` worktree. Both have clean tracked
files after validation. Do not give either checkout directly to an eval agent:
they contain upstream solution history and current regression tests.

The [candidate source manifest](../evals/t3code/cases.json) records prompts, provenance,
target files, commands, patch checksums, and observed outcomes. The patches
under `evals/t3code/validation-patches` introduce bugs for validation, not solutions.

## Verified on 2026-10-06

Each patch was applied independently to the pinned reference, its targeted
test file was run, then the patch was reversed. Failures below are actual
regression assertions, not dependency/setup failures.

| Case | Realistic behavior | Buggy failures / tests | Fixed passes |
| --- | --- | --- | --- |
| trimmed-ids | Unicode whitespace validation and schema round trips | 92 / 103 | 103 |
| worker-recovery | Failed items, cancellation, and worker shutdown | 2 / 3 | 3 |
| cache-pruning | Expiration without deleting unrelated files | 1 / 11 | 11 |
| concurrent-settings | Settings updates during an in-flight save | 1 / 11 | 11 |
| indexeddb-recovery | Forced-close recovery with concurrent readers | 1 / 10 | 10 |

After restoring all five patches, a combined targeted run passed all five
files and all 138 tests. Node 24.18.0, pnpm 11.10.0, Vitest 5.0.1.
Dependencies were installed with a frozen lockfile, scoped to relevant
workspaces, with lifecycle scripts disabled. No repository-wide tests,
typechecks, GUI, live provider services, or T3 user data were used.

The first four cases reverse only the relevant production slice of historical
fixes. The ID case excludes mobile-route changes; the settings case excludes
the unrelated adapter race in the same upstream commit.

The full historical IndexedDB reversal changed the internal DatabaseHandle
API and was rejected as an unsuitable baseline. Its final patch reintroduces
only the missing forced-close invalidation while preserving the current API.
This is a narrow historical-bug reconstruction, not a complete recreation of
the old checkout or all storage defects in the original upstream change.

## Packaging and app validation completed

- Each case repository contains exactly one clean baseline commit and no remote.
  All five held-out test files were excluded before that commit, so they are not
  recoverable from its Git history. The buggy state is committed, not a starting
  patch that could contaminate scored diffs.
- Verifiers are stored separately and installed through the app bundle handler
  after the agent-diff checkpoint. Dependencies were installed offline from the
  local cache using the frozen lockfile, without lifecycle scripts. Workspaces
  resolve their own source; they do not symlink to the fixed upstream checkout.
- The app command scorer classified all five buggy cases as fail and all five
  reference repairs as pass. Reference diffs changed only each allowed production
  file; held-out files remained unchanged. Validation worktrees were removed.
- The app case service independently validated and published all five revisions,
  then froze suite 1/version 1. Database migrations 1–8 were applied. This used a
  new test database, not the normal application's database.
- Packaging safety tests cover excluded Git blobs, unsafe archive paths, remotes,
  extra history, visible ignored verifiers, and refusal to import into an already
  initialized app process. Live-import tests check database/PID matching and
  keeping authentication tokens out of output. Pilot guards prevent silent reruns
  and multi-attempt/network-enabled preflight. Backend lint and all 87 tests pass.

## Active UI import

The running UI was confirmed to use `backend/agent_workbench.db` via its backend's
open files, rather than an assumed Electron user-data path. The five cases were
imported through that backend's authenticated local API, validated again, and
published as cases/revisions 1–5. Suite 1/version 1 is frozen. Existing app state
was not replaced; sessions/messages/runs remained 3/17/5 before and after import.
A consistent SQLite backup was made and retained at
`backend/agent_workbench.db.t3-import-4ql8b_ht.bak` (gitignored, contains private app data).
No backend restart or application rebuild was required.

Case repositories are now persistent under `.eval-cases/t3code/<case-id>`
(gitignored), independent of the temporary packaging directory. They retain
the same pinned baseline commits, no remote, and no held-out tests. Verifier
bundles are stored in the active app's artifact store.

The Evals page cached its lists, so the running app was refreshed. Native UI
inspection then showed all five case names with Published/Valid status.
[Live import evidence](evidence/t3code-live-import-2026-10-06.json) records the
database, backup, persistent repositories, and UI verification.

Records: [package evidence](evidence/t3code-package-2026-10-06.json) and
[app import evidence](evidence/t3code-import-2026-10-06.json).
Generated repositories occupy approximately 2.3 GiB under
`/private/tmp/uiagg-t3-evals-f4uhhtoh`; app state is under
`/private/tmp/uiagg-t3-app-sutx2iph`. These are temporary local artifacts and may
be cleared by the OS; the scripts can regenerate them. Recorded commit SHAs pin
this preparation run; freshly generated initial commits may have different SHAs.

Reproduce from the UIagg root after installing the pinned upstream's scoped dependencies:

```sh
backend/.venv/bin/python backend/tools/prepare_t3_evals.py
backend/.venv/bin/python backend/tools/import_t3_evals.py <printed-package-directory>
```

The isolated importer always creates a fresh test database. The live importer
is a separate explicit opt-in command:

```sh
backend/.venv/bin/python backend/tools/import_t3_live.py <package-directory> --database <confirmed-active-db> --backend-pid <confirmed-backend-pid>
```

It confirms the selected backend has that database open, backs up SQLite, keeps
credentials in memory, and uses the live API rather than copying database rows.
It can reuse matching published cases without overwriting unrelated records.

## Next: agent pilot and comparison

1. Completed: bounded one-case pilot with the configured model explicitly recorded,
   medium reasoning, network-disabled shell sandbox, trace review, and cleanup.
2. Completed: all five cases in one paired medium/high experiment, with identical
   generalized scope guards and one attempt per case/configuration. Medium passed
   4/5 and high 3/5; verdict inconclusive. See [the comparison report](evals-t3code-comparison-report.md).
3. Clarify allowed-file scope in future case prompts, review failed patches, and
   complete interactive packaged-app release checks. Do not treat this small
   public-code comparison as a broad configuration ranking.

Baseline/reference checks establish detectable local regressions; the completed
comparison adds limited agent scenario evidence.
The upstream is public, so hidden local history does not eliminate possible
model training contamination. Keeping verifiers outside worktrees is not an
OS/container read boundary: an unrestricted agent could read sibling directories
or the original source checkout. Strong adversarial secrecy requires separate
filesystem isolation; ordinary pilots must prohibit and inspect out-of-scope
reads, and must not describe this as a contamination-proof benchmark.
This small curated suite is not representative
of every repository task or a basis for broad statistical claims.
