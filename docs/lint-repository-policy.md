# Lint and repository policy

The backend's Ruff configuration is now explicit in `backend/pyproject.toml`, rather than relying on default or machine-specific settings. CI runs both `ruff check .` and `ruff format --check .`.

Enabled rule families: baseline syntax/undefined names (`E4`, `E7`, `E9`, `F`), imports (`I`), bug patterns (`B`), async code (`ASYNC`), modernization (`UP`), simplification (`SIM`), security heuristics (`S`), broad exception catches (`BLE`), and unused suppressions (`RUF100`). See [Ruff's configuration documentation](https://docs.astral.sh/ruff/configuration/).

Runtime and CI still require Python 3.14. Ruff uses a Python 3.13 **code-style target** to retain and enforce readable parenthesized multi-exception handlers; this does not promise Python 3.13 runtime compatibility. Formatting no longer undoes that syntax. The shared response TypedDict definitions use class syntax without changing generated frontend types.

## Fixes and scoped exceptions

- Flagged production directory checks, path resolution, and home-directory lookup in async runtime, Git, worktree, scorer, configuration capture, and reconciliation paths now run through `asyncio.to_thread`. Flagged Evals utility reads also move off the event loop.
- Process-not-found cleanup uses `contextlib.suppress` while preserving termination behavior. The scheduler's broad exception catch remains deliberately scoped to an attempt boundary: it persists infrastructure failures and prevents a stranded queue. `BLE001` and unused-suppression checking are now active.
- Production synchronous Git calls have local, explained `S603`/`S607` suppressions: fixed Git executable/operations and argument-vector execution, not a shell. This is not a general assertion that every subprocess input is safe.
- Test-only exceptions cover assertions, fake secrets, illustrative paths, fixture subprocesses, synchronous temporary-filesystem setup, and bounded polling of external child/file state. Operator-run tooling suppresses assertions and selected subprocess heuristics; other security/async rules remain active. There are no global rule ignores.
- The Evals tools' `Rpc` helper only accepts HTTP(S) origins on `127.0.0.1`, `localhost`, or `::1`, with no URL credentials, path prefix, query, or fragment. Its opener disables ambient proxies and all redirects to keep the backend token local. This affects operator tools, not the main app transport. Localhost still relies on the host's normal name resolution; this is not a hostile-host security boundary.
- Import evidence row counts use fixed SQL queries, avoiding interpolated table names.

## Metadata and ignored documents

The virtual backend project is named `agent-workbench-backend` with a product-specific description. The offline-refreshed lockfile contains the same third-party dependencies and versions; only the local project name/order changed. The app executable, release version, import paths, and database layout are unchanged.

PRD ignores now match document names `PRD.*`, `PRD-*`, `PRD_*`, or names ending in `-PRD`, `_PRD`, or `.PRD`, with case-insensitive `.md`, `.txt`, `.pdf`, or `.docx` extensions. Source names and ordinary documents merely containing `prd` are not hidden. Use those conventions for private PRDs; other formats or naming conventions require a specific ignore rule. The existing `docs/evals-mode-prd.md` remains ignored and was not deleted or added to Git. Ignore rules do not untrack already tracked files.

## Verification

Fourteen new tests check ignore boundaries, metadata/lockfile consistency, required lint families, parenthesized production exception handlers, RPC URL rejection, proxy/redirect restrictions, and static query evidence. All 160 backend tests, frontend contract/regression checks, production build, both linters, backend formatting, generated-contract drift, and offline lockfile verification pass locally. Tests use disposable fixtures, not paid agents or the application database. Hosted CI and a rebuilt installer remain unverified for this batch.

Follow-up scaling work is implemented in [catalog pagination](catalog-pagination.md): bounded ID-cursor queries and complete UI catalog loading beyond 500 sessions, without changing list response shapes. Lazy rendering remains a separate scaling improvement.
