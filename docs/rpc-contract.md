# Shared RPC contract

`backend/rpc_contract.py` is the authoritative map of all 59 public RPC methods, their existing Pydantic parameter models, and Python response shapes. Existing record models remain in `database/schemas.py`; dictionary responses use TypedDict shapes interpreted by Pydantic. The HTTP and WebSocket dispatcher validates inputs before invoking handlers and validates successful JSON results against the shared contract. Invalid inputs remain `-32602`; invalid server responses become a payload-free `-32603` error. Successful response payloads are not rewritten.

## Updating the contract

1. Update the backend parameter/response definitions and method map together with the handler.
2. Regenerate the checked-in TypeScript file:

   ```sh
   cd backend
   .venv/bin/python tools/generate_rpc_contract.py
   .venv/bin/python tools/generate_rpc_contract.py --check
   cd ..
   npm --prefix frontend run test:contract
   npm --prefix frontend run build
   ```

`frontend/src/generated/rpcContract.ts` contains input types, serialized record/response types, and a method map. Generation uses Pydantic's [validation and serialization JSON-schema modes](https://github.com/pydantic/pydantic/blob/main/docs/concepts/json_schema.md): defaulted input fields may be omitted, nullable values remain nullable, and serialized dates are strings. The generator has no additional dependencies and rejects unsupported schema constructs instead of silently producing an untyped fallback. Frontend-only builds use the checked-in file and do not require Python.

Both live and demo transports now infer results from `request('method', params)`. Callers cannot assert arbitrary result types. Unknown methods, missing/wrong parameters, invalid literals, and incorrect response usage fail TypeScript checks. Git actions use separate calls for staging, committing, and pushing so their required fields stay correlated with the method. UI-only optimistic messages and partial live events remain projections of generated stored-record types; the codebase-map display shape is still local.

The actual wire format exposed nullable case revisions and optional fields on unavailable earlier-run diffs. The generated contract preserves these instead of strengthening them incorrectly; the case UI now handles a missing revision explicitly.

## Checks and boundaries

Twelve backend tests check handler/method-map completeness, matching parameter models, deterministic generation, defaults/constraints, nullable and optional output fields, fail-closed generation, and input/output validation behavior. Compile-only frontend tests use `@ts-expect-error` assertions for invalid calls and result usage, including both transports. Run generated-file drift checks and compile these assertions locally alongside existing regressions.

TypeScript cannot enforce numeric ranges, string patterns, filesystem rules, authorization, or semantic scorer configuration; those remain backend checks. Open-ended event payloads and configuration/scorer dictionaries remain `unknown`-valued objects. The frontend does not perform runtime schema validation of incoming frames; its typed boundary relies on the updated backend. Extra legacy fields are not globally rejected. Response validation happens after handler execution and does not roll back completed side effects; contract errors must not trigger automatic mutation retries.

The subsequent [handler refactor](rpc-handlers.md) replaced the dispatch chains with registered domain handlers while preserving this contract. Neither step changes database schemas or repackages the installer. Backend schema imports initialize the SQLAlchemy engine configuration but the generator does not connect to SQLite, run migrations, or launch agents.
