import recording from './data/portfolioBenchmark.json' with { type: 'json' }
import { recordedEvalRequest } from './recordedEvals.ts'
import type { PortfolioRecording } from './recordedEvals.ts'

export const portfolioRecording = recording as PortfolioRecording

export function demoEvalRequest(method: string, params: Record<string, unknown>): unknown {
  return recordedEvalRequest(portfolioRecording, method, params)
}
