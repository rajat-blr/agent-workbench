# Registered RPC handlers

The core and Evals routers now use `@rpc("method.name")` registrations and immutable dictionary lookups instead of long dispatch chains. All 59 public methods remain covered: 27 core methods and 32 Evals methods.

| Owner | Handler modules |
| --- | --- |
| `RpcDispatcher` in `backend/main.py` | `rpc_handlers/health.py`, `workspace.py`, `session.py`, `run.py` |
| `EvalService` in `backend/evals/service.py` | `evals/cases.py`, `suites.py`, `configs.py`, `experiments.py`, `attempts.py` |
| Shared support | `rpc_registry.py`, `rpc_handlers/common.py`, `evals/common.py` |

`EvalService` is now a 49-line composition/routing class, down from 1,718 lines. `main.py` is 522 lines; it retains server startup, transport/authentication, response validation, persistence callbacks, and shared lookup/locking context. Domain mixins use the service's existing runtime, scheduler, artifact store, worktree service, and locks. Registration binds handlers to each instance; it never keeps a global service instance.

## Adding a method

1. Add the parameter/result entry to `rpc_contract.py`.
2. Add an async handler to the relevant domain class, decorated with `@rpc("method.name")`. Its signature is `(self, method, params, db)`; the method argument supports aliases sharing one implementation.
3. Regenerate frontend types and run contract/registry tests plus affected domain tests.

The decorator rejects unknown methods, empty/duplicate names, synchronous handlers, and stacked registrations. Registry construction rejects duplicate inherited registrations; cached definitions and per-instance bound maps are read-only. Registration is static: runtime monkey-patching of handler definitions is not a supported extension mechanism.

## Verification and boundaries

Ten new registry tests check registration errors, immutable/per-instance binding, aliases, direct health-handler testing, unknown methods, and exact argument routing across all 59 methods. Contract tests now inspect registered handlers rather than dispatch branches and verify completeness and parameter-model agreement. Existing integration tests exercise real handler behavior with disposable SQLite/Git/worktree fixtures.

A one-time AST comparison verified all 59 extracted handler bodies against the pre-refactor source. The only adapted call injects chat-start failure persistence through the dispatcher so it keeps the original callback and session-factory behavior. Public method names, response/error shapes, transaction boundaries, locks, scheduling, and paid-run behavior were not intentionally changed. `EvalServiceError` and the existing revision-payload import remain available from `evals.service` for compatibility.

Case validation remains the largest domain function and is not split into a separate validation pipeline in this batch. This is backend organization work, not a UI redesign or a new release installer.

Local verification on 2026-10-09: all 146 backend tests, 33 frontend/Electron tests, compile-only contract assertions, both linters, generated-type drift checks, the production frontend build, and the hidden Electron smoke pass. A fresh PyInstaller backend built in a temporary directory and passed authenticated startup, workspace/session/history, case/suite/configuration creation and listing, and empty experiment-list checks against a disposable database with agent execution disabled. The existing installer and user's application database were not changed; hosted CI and interactive real-agent QA were not run.
