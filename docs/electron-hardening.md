# Electron hardening

## Desktop safeguards

- Packaged content uses the standard, secure `workbench://app` protocol, restricted to real files below the bundled `dist` directory. Path traversal and symlink escapes are rejected. The backend permits this renderer origin while retaining legacy origins for existing clients.
- CSP is injected into response headers with the exact configured loopback HTTP(S)/WebSocket origin. Remote connections, other loopback ports, inline production scripts, eval, frames, forms, and object embeds are disallowed. Local styles permit inline declarations for existing React layout styles.
- Development additionally permits Vite's fixed loopback origin and inline refresh bootstrap. These exceptions are absent from the production policy. `BACKEND_URL` must be a loopback origin without credentials or a path.
- New windows, document/frame navigation, redirects, and webview attachment are denied. Main-document HTTP(S) links use the same validated external-URL path as desktop IPC and open in the system browser. Arbitrary file/data/javascript/custom-scheme links are rejected.
- Desktop IPC requires the trusted app document's main frame; permissions are denied by default. Existing sandboxing, context isolation, and disabled Node integration remain enabled.
- An unexpected owned-backend exit after startup displays a native error with recovery guidance. No automatic restart retries potentially active work. Startup failures use the existing startup error path; normal quit does not display a crash alert. Externally managed backends remain the external owner's responsibility.

## Shutdown behavior and limits

On POSIX, Electron starts its backend in a dedicated process group. Normal quit sends SIGTERM and waits up to ten seconds before SIGKILL, then waits up to two seconds for exit. Windows uses direct-child signaling instead of POSIX groups.

The ASGI shutdown path first cancels and joins eval scheduler tasks so setup/scorer process-group cleanup executes, then stops runtime agents before closing SQLite connections. Runtime shutdown gives agent watchers five seconds to finish; remaining agent groups receive SIGKILL, including descendants retaining pipes after their parent exits.

These steps improve normal quit. They do not guarantee cleanup after Electron/backend hard crashes, OS termination, descendants that create their own sessions, or a stuck persistence/filesystem operation that consumes the outer grace period. Killing the backend group alone cannot reach Codex processes launched in their own groups. Interrupted experiments remain subject to startup reconciliation and explicit resume; no automatic paid reruns occur.

## Verification

Unit tests cover exact-origin CSP, development exceptions, header replacement, URL validation, popup/navigation guards, restricted protocol file serving, backend failure reporting, graceful termination, escalation, and already-exited children. Backend regression fixtures cover scheduler cleanup and a SIGTERM-resistant agent/descendant heartbeat.

The hidden Electron smoke test renders the production UI, checks trusted preload IPC and actual loopback HTTP/WebSocket access, rejects remote/other-port connections and inline script injection, verifies external-link routing, and confirms the app document did not navigate. This exercises production renderer policy, not the signed installer or a real Codex session. Run it after `npm run build` with `npm run test:electron:smoke`.

Implementation follows [Electron's security guidance](https://www.electronjs.org/docs/latest/tutorial/security).

Local verification on 2026-10-09: 113 backend tests, ten Electron unit tests, two demo tests, frontend type-check/production build, both linters, and the hidden Electron smoke passed. Git whitespace checks passed. Rebuilt/signed release artifacts have not been exercised.
