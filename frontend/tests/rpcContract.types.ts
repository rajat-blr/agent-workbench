// Compile-only regressions: every @ts-expect-error must remain an error.
import type { RpcTransport, RpcResult } from '../src/generated/rpcContract'
import type { RpcClient } from '../src/rpcClient'
import type { DemoRpcClient } from '../src/demoRuntime'

declare const rpc: RpcTransport
declare const live: RpcClient
declare const demo: DemoRpcClient
const transports: RpcTransport[] = [live, demo]
void transports

rpc.request('health.check').then(result => {
  const status: 'ok' = result.status
  void status
  // @ts-expect-error Health response is not a session.
  void result.session_id
})
rpc.request('session.create', { workspace_id: 1 }) // provider defaults server-side
rpc.request('session.list') // optional filter
rpc.request('session.list', { workspace_id: 1 })
rpc.request('workspace.list', { before_id: 0, limit: 200 })
rpc.request('session.list', { before_id: 50, limit: 200, workspace_id: 1 })
// @ts-expect-error catalog cursors are numeric IDs, not strings
rpc.request('workspace.list', { before_id: '50' })
rpc.request('session.history', { session_id: 1 }).then(history => {
  const id: number = history.session.id
  void id
})
rpc.request('eval.config.capture', { name: 'Baseline', model: null })
rpc.request('workspace.git_stage', { workspace_id: 1, paths: ['src/app.ts'], expected_branch: 'feature' })
rpc.request('workspace.git_commit', { workspace_id: 1, message: 'Change', expected_branch: 'feature', index_token: 'token' })
rpc.request('workspace.git_push', { workspace_id: 1, remote: 'origin', branch: 'feature', expected_branch: 'feature' })
declare const decision: 'accept' | 'revert'
rpc.request(`run.diff.${decision}`, { session_id: 1, run_id: 2 })

// @ts-expect-error Unknown method cannot be called.
rpc.request('session.typo', { session_id: 1 })
// @ts-expect-error Required parameters cannot be omitted.
rpc.request('session.send')
// @ts-expect-error Required send content cannot be omitted.
rpc.request('session.send', { session_id: 1 })
// @ts-expect-error Numeric IDs cannot be strings.
rpc.request('session.get', { session_id: '1' })
// @ts-expect-error Unknown parameter is rejected.
rpc.request('session.history', { session_id: 1, cursor: 5 })
// @ts-expect-error Literal modes are checked.
rpc.request('session.send', { session_id: 1, content: 'Hi', mode: 'invalid' })
// @ts-expect-error Staging needs paths, not a commit message.
rpc.request('workspace.git_stage', { workspace_id: 1, expected_branch: 'main', message: 'Oops' })
// @ts-expect-error Commit requires the reviewed index token.
rpc.request('workspace.git_commit', { workspace_id: 1, expected_branch: 'main', message: 'Oops' })
// @ts-expect-error Callers cannot assert an arbitrary result type.
rpc.request<{ run_id: string }>('session.send', { session_id: 1, content: 'Hi' })
// @ts-expect-error Live transport is also checked.
live.request('session.get')
// @ts-expect-error Demo uses the same checked contract.
demo.request('eval.experiment.get', { experiment_id: '1' })
declare const run: RpcResult<'run.get'>
// @ts-expect-error Eval runs may have no chat session.
const sessionId: number = run.session_id
void sessionId
