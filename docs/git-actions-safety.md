# Reviewed Git actions

Current source build; rebuild/restart to use the updated UI and RPC contract. No real workspace staging, commits, or remote pushes were performed while implementing this change.

## UI workflow

- **Select files…** refreshes Git status and opens an unchecked file list. Select only intended changes. Secret-like paths and generated-output directories carry advisory warnings, not automatic exclusions or selections. Staging applies the current full file contents; hunk staging and unstaging are not implemented.
- **Review & commit…** refreshes and lists every staged file, including changes staged through another tool. Provide a message and confirm. A staged-diff fingerprint rejects a review that has already become stale.
- **Push…** refreshes status, defaults to the current local branch and `origin` when configured, and lets the user choose a configured remote and destination branch. Confirmation shows the source and destination. Push does not switch branches or force updates; normal Git non-fast-forward protections still apply.

Repository-root, active-run, and checked-out-branch guards apply. A branch changed since review is rejected. Detached HEAD and repositories without configured remotes show explanatory states. Workspace-keyed components reset review state when switching projects; failed/stale reviews can be reloaded.

## Backend safeguards

Status uses Git's NUL-delimited porcelain format with individual untracked files, preserving spaces, newlines, and rename origins. Staging requires explicit paths currently listed as unstaged. No directory-wide `git add .`, implicit selection, or arbitrary pathspec expansion remains. Git receives literal pathspecs after an option terminator; tests include dash-prefixed and pathspec-like filenames.

Commit requires the reviewed branch and SHA-256 fingerprint of that branch plus the staged binary diff. Push accepts configured remote names only and validates its destination as `refs/heads/<branch>` before pushing `HEAD` there. Commands use argument arrays, not a shell. Git hooks, credentials, remote configuration, and external tools remain user-controlled.

These are reviewed-input safeguards, not cross-process transactions. An external CLI or hook can still alter the index/ref after validation. Review file contents/diffs as needed; advisory filename hints are not a secret scanner. Git mutations can fail after partial Git-internal work; refresh status after an error rather than assume rollback.

The legacy `workspace.git_push_main` remains for compatibility with main/origin-only clients. `workspace.git_stage` now requires `paths` and `expected_branch`; `workspace.git_commit` additionally requires `expected_branch` and `index_token`. Old clients must update rather than fall back to broad staging. Full signatures are in [backend documentation](../backend/README.md).

## Checks

Thirteen Git backend tests cover local stage/commit/push, selective staging without sweeping `.env` or build output, literal filenames, rejected directories/traversal/unknown paths, duplicate/empty selections, stale index/branch reviews, rename/deletion handling, feature-branch destination pushes, invalid remotes/refnames, detached HEAD, nested roots, and active runs.

Three frontend selection tests cover explicit-only payloads, stale/invalid selections, and advisory warnings. Run them locally via `npm run test:git`. Frontend build/lint and the existing Electron security smoke exercise the rebuilt app, but do not constitute interactive verification of every Git dialog. Backend mutation tests use disposable repositories and local bare remotes only.

Local verification on 2026-10-09: all 124 backend tests passed, plus three Git selection tests, two demo tests, ten Electron unit tests, the hidden Electron smoke, frontend production build/type checks, both linters, workflow YAML parsing, and Git whitespace checks.

Format and command handling follow [Git status](https://git-scm.com/docs/git-status), [literal pathspec](https://git-scm.com/docs/git), and [push](https://git-scm.com/docs/git-push) documentation.
