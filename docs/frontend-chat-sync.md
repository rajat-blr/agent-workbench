# Frontend chat synchronization

The chat's messages, activity events, session generation, and sequence cursor now live in a React-independent `ChatSyncStore`, exposed through `useChatSync` and `useSyncExternalStore`. This extracts reconciliation logic, not all application state.

## Safeguards

- Selection resets the store synchronously and invalidates old requests, including switching away and back to the same session.
- History merges with live events received during the fetch, deduplicates durable event identities, preserves distinct identical assistant messages, and never decreases the cursor.
- Paginated history retains the latest complete conversation and rejects pages that do not advance. Subscribe-first reconciliation no longer reruns on every session status update.
- Send acknowledgements, cancellation, diff responses, and Git status refreshes are session-generation guarded. Newer history/Git requests supersede older responses.
- Obsolete WebSockets cannot deliver events into a replacement connection. Replacement/closure rejects pending calls; close-before-open and failed sends settle promises and release timers.
- `react/exhaustive-deps` is enabled; the ineffective suppressions in App and Evals subscriptions were removed. Evals subscriptions ignore responses after cleanup.

## Verification

Run `npm --prefix frontend run test:chat` with Node 24. Eighteen deterministic tests exercise selection races, live/history merging, duplicate handling, late acknowledgements, pagination, cleanup, status mapping, WebSocket replacement, reconnect scheduling, timeouts, malformed frames, and send failures. Run these locally alongside demo, Git, and Electron tests.

These are store and transport tests with deferred promises and fake sockets/timers, not rendered chat interaction tests. The hidden production Electron smoke separately checks renderer startup and security policy. No real agent calls or application database mutations are needed.

Remaining interactive QA: switch sessions during a live response, reconnect during a run, manually sync while events arrive, and review a diff while switching workspaces. This batch does not refactor every workspace CRUD flow or create a fully typed frontend/backend RPC contract. Rebuild/restart to use the source changes; no installer was repackaged.
