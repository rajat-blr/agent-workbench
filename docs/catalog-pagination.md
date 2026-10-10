# Workspace and chat catalog pagination

`workspace.list` and `session.list` retain their array responses and accept:

- `limit`: 1–500, default 500.
- `before_id`: omit/null for legacy display ordering; use `0` to start an ID-descending scan, then the last returned ID for each next page.
- `workspace_id`: optional positive session filter, applied to every page.

Stop when a page contains fewer than `limit` records. An exact multiple needs one final empty request. Every query is bounded, including legacy workspace listing (previously unbounded). Legacy callers receive only the first page; clients needing the complete catalog must follow cursors.

The main application requests 200 records per page, loads both catalogs, and restores workspace-name / session-activity presentation ordering with deterministic ID tie-breakers. The 500-session limit no longer truncates the UI. Selection or connection changes invalidate the load and stop requesting further pages; partial results and failed loads are not applied. Demo endpoints support the same pagination parameters.

Stable IDs prevent renames or activity updates from shifting records between pages. Inserts with IDs above the first page are picked up on the next catalog reload; deleted records may disappear during loading. This is not a transactional snapshot across requests. The UI still keeps and renders the complete catalog in memory: lazy loading and sidebar virtualization are separate future scaling work.

Seven backend cases cover bounds and a 601-record traversal for both catalogs, updates/inserts between pages, empty results, legacy ordering and workspace filtering. Six frontend tests cover traversal beyond 500, exact/empty termination, cancellation, malformed cursors, failures, sorting and demo parity. Run `pytest -q tests/test_catalog_pagination.py` and `npm run test:catalog` in their respective directories. These use disposable fixtures, not the application database or agents.

The [packaged verification](catalog-packaged-verification.md) additionally checks 601 workspaces/chats in the actual desktop renderer, mouse selection of the oldest chat, independent sidebar scrolling and screenshot layout. Electron file-reveal authorization follows bounded workspace pages too.
