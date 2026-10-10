import type { StoredActivityEvent, StoredMessage } from "./generated/rpcContract"
export type { SessionStatus, RunStatus, MessageRole, Workspace, GitFile, GitStatus, Session, Run, StoredMessage, StoredActivityEvent, SessionHistory, RunDiffFile, RunDiff, EvalCaseRevision, EvalCase, EvalSuite, EvalConfig, EvalAttemptSummary, EvalResults, EvalExperiment, EvalStep, EvalAttemptEvent, EvalScorerOutput, EvalAttemptDetail, EvalPreflight, EvalExperimentEvent } from "./generated/rpcContract"

// UI projections can include live events and optimistic messages before persistence.
export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "reconnecting"
export type Message = Pick<StoredMessage, "role" | "content"> & Partial<Pick<StoredMessage, "run_id">>
export type ActivityEvent = Pick<StoredActivityEvent, "type"> & Partial<Omit<StoredActivityEvent, "type" | "payload">> & { payload: { content?: string; [key: string]: unknown } }
export type CodebaseMap = { nodes: { id: string; label: string; summary: string; files: string[] }[]; edges: { source: string; target: string; label: string }[] }
export type RpcResponse<T> = { jsonrpc: '2.0'; id: number | string | null; result?: T; error?: { code: number; message: string; data?: unknown } }

import { RpcClient } from './rpcClient'
export { RpcClient } from './rpcClient'

export const isDemoMode = import.meta.env.VITE_APP_MODE === 'demo'
export const rpcClient = isDemoMode ? new DemoRpcClient() : new RpcClient()
import { DemoRpcClient } from './demoRuntime'
