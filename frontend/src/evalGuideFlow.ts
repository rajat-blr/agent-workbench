import type { RpcClient } from './rpcClient'
import type { EvalCase, EvalConfig, EvalExperiment, EvalSuite } from './generated/rpcContract'

type TaskInput = { existing?: EvalCase; title: string; prompt: string; workspaceId: number; baseSha: string; command: string; expectation: string }
export type ReasoningInput = { efforts: string[]; model: string; preamble: string; samples: number }
type Callbacks = { onCase: (value: EvalCase) => void; onSuite: (value: EvalSuite) => void; onConfig: (value: EvalConfig) => void; onExperiment: (value: EvalExperiment) => void; progress: (message: string) => void }

/** Successful writes are retained so later failures can resume the same setup. */
export class EvalGuideFlow {
  private task: EvalCase | null = null
  private suite: EvalSuite | null = null
  private configs: EvalConfig[] = []
  private settingsKey = ''
  private experiment: EvalExperiment | null = null
  private request: RpcClient['request']
  private callbacks: Callbacks
  constructor(request: RpcClient['request'], callbacks: Callbacks) { this.request = request; this.callbacks = callbacks }

  private rememberTask(value: EvalCase) { this.task = value; this.callbacks.onCase(value) }
  private rememberSuite(value: EvalSuite) { this.suite = value; this.callbacks.onSuite(value) }

  async prepareTask(input: TaskInput) {
    this.callbacks.progress('Preparing task…')
    if (!this.task && input.existing) this.rememberTask(input.existing)
    if (this.task?.latest_revision?.status !== 'published') {
      if (!input.title.trim() || !input.prompt.trim() || !input.workspaceId || !input.command.trim()) throw new Error('Enter a task name, workspace, prompt, and test command.')
      if (/["'|;&<>`$]/.test(input.command)) throw new Error('Use a test command with plain arguments. For complex verification, put the check in a script.')
      if (!this.task) this.rememberTask(await this.request('eval.case.create', { title: input.title.trim(), prompt: input.prompt.trim(), workspace_id: input.workspaceId, base_sha: input.baseSha.trim() || null }))
      const revision = this.task!.latest_revision
      if (!revision) throw new Error('Task revision is unavailable.')
      this.rememberTask(await this.request('eval.case.update_draft', {
        case_id: this.task!.id, revision_id: revision.id, title: input.title.trim(), prompt: input.prompt.trim(), base_sha: input.baseSha.trim() || revision.base_sha,
        scorer_spec: [{ type: 'command', key: 'verifier', argv: input.command.trim().split(/\s+/) }], path_policy: { base_expectation: input.expectation },
      }))
      this.callbacks.progress('Checking the task and test command…')
      this.rememberTask(await this.request('eval.case.validate', { case_id: this.task!.id, revision_id: revision.id }))
      if (this.task!.latest_revision?.validation_status !== 'valid') {
        const problems = this.task!.latest_revision?.validation_details.problems
        throw new Error(Array.isArray(problems) && problems.length ? problems.join('\n') : 'Validation failed. Check the base commit and test command, then try again.')
      }
      this.rememberTask(await this.request('eval.case.publish', { case_id: this.task!.id, revision_id: revision.id }))
    }
    if (!this.task?.latest_revision) throw new Error('Task revision is unavailable.')
    this.callbacks.progress('Preparing evaluation…')
    if (!this.suite) this.rememberSuite(await this.request('eval.suite.create', { name: `${this.task.title} · guided evaluation` }))
    if (this.suite!.latest_version.status !== 'frozen') {
      this.rememberSuite(await this.request('eval.suite.update_draft', { suite_id: this.suite!.id, version_id: this.suite!.latest_version.id, case_revision_ids: [this.task.latest_revision.id] }))
      this.rememberSuite(await this.request('eval.suite.freeze', { suite_id: this.suite!.id, version_id: this.suite!.latest_version.id }))
    }
  }

  private plan(input: ReasoningInput) {
    if (!this.task || !this.suite || !this.configs.length) throw new Error('Prepare a task and reasoning settings first.')
    return { name: `${this.task.title} · ${input.efforts.join(' vs ')} reasoning`, suite_version_id: this.suite.latest_version.id, config_snapshot_ids: this.configs.map((item) => item.snapshot.id), samples_per_case: input.samples, concurrency: 1, timeout_seconds: 1800 }
  }

  async review(input: ReasoningInput) {
    if (!this.task?.latest_revision || this.suite?.latest_version.status !== 'frozen') throw new Error('Prepare a task first.')
    if (!input.efforts.length || input.efforts.length > 2 || new Set(input.efforts).size !== input.efforts.length || input.efforts.some((effort) => !['low', 'medium', 'high', 'xhigh'].includes(effort))) throw new Error('Choose one or two reasoning levels.')
    if (!Number.isInteger(input.samples) || input.samples < 1 || input.samples > 10) throw new Error('Choose between 1 and 10 runs per level.')
    const key = JSON.stringify([input.efforts, input.model.trim(), input.preamble])
    if (key !== this.settingsKey) { this.settingsKey = key; this.configs = [] }
    for (let index = this.configs.length; index < input.efforts.length; index++) {
      const effort = input.efforts[index]
      this.callbacks.progress(`Saving ${effort} reasoning settings…`)
      const config = await this.request('eval.config.capture', { name: `${this.task.title} · ${effort} reasoning`, workspace_id: this.task.latest_revision.workspace_id, model: input.model.trim() || null, reasoning_effort: effort, instruction_preamble: input.preamble, sandbox_policy: { mode: 'workspace-write', network: false } })
      this.configs.push(config)
      this.callbacks.onConfig(config)
    }
    this.callbacks.progress('Reviewing evaluation…')
    return this.request('eval.experiment.preflight', this.plan(input))
  }

  async start(input: ReasoningInput) {
    this.callbacks.progress('Creating evaluation…')
    if (!this.experiment) {
      this.experiment = await this.request('eval.experiment.create', this.plan(input))
      this.callbacks.onExperiment(this.experiment)
    } else {
      this.experiment = await this.request('eval.experiment.get', { experiment_id: this.experiment.id })
    }
    if (this.experiment.status === 'ready') {
      this.callbacks.progress('Starting evaluation…')
      await this.request('eval.experiment.start', { experiment_id: this.experiment.id })
    }
    this.experiment = await this.request('eval.experiment.get', { experiment_id: this.experiment.id })
    this.callbacks.onExperiment(this.experiment)
  }
}
