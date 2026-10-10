import { useState } from 'react'
import { rpcClient } from './runtime'
import { EvalGuideFlow } from './evalGuideFlow'
import type { EvalCase, EvalConfig, EvalExperiment, EvalPreflight, EvalSuite, Workspace } from './runtime'

type Props = {
  live: boolean
  workspaces: Workspace[]
  cases: EvalCase[]
  preferredWorkspaceId?: number
  onCase: (value: EvalCase) => void
  onSuite: (value: EvalSuite) => void
  onConfig: (value: EvalConfig) => void
  onExperiment: (value: EvalExperiment) => void
}
const efforts = ['low', 'medium', 'high', 'xhigh']
const effortLabel = (value: string) => value === 'xhigh' ? 'Extra-high' : value[0].toUpperCase() + value.slice(1)

export function EvalGuide({ live, workspaces, cases, preferredWorkspaceId, onCase, onSuite, onConfig, onExperiment }: Props) {
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [existingId, setExistingId] = useState(0)
  const [workspaceId, setWorkspaceId] = useState(preferredWorkspaceId ?? 0)
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [command, setCommand] = useState('')
  const [baseSha, setBaseSha] = useState('')
  const [expectation, setExpectation] = useState('required_scorer_fails')
  const [model, setModel] = useState('')
  const [preamble, setPreamble] = useState('')
  const [selectedEfforts, setSelectedEfforts] = useState(['medium', 'high'])
  const [samples, setSamples] = useState(1)
  const [preflight, setPreflight] = useState<EvalPreflight | null>(null)
  const [displayTask, setDisplayTask] = useState<EvalCase | null>(null)
  const [hasExperiment, setHasExperiment] = useState(false)
  const [flow] = useState(() => new EvalGuideFlow(rpcClient.request.bind(rpcClient), {
    onCase: (value) => { setDisplayTask(value); onCase(value) },
    onSuite, onConfig,
    onExperiment: (value) => { setHasExperiment(true); onExperiment(value) },
    progress: setBusy,
  }))
  const locked = displayTask?.latest_revision?.status === 'published'
  const selectedWorkspace = workspaceId || workspaces[0]?.id || 0
  const published = cases.filter((item) => item.latest_revision?.status === 'published')
  const perform = async (action: () => Promise<void>) => {
    if (busy) return
    setError('')
    try { await action() }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not complete this step.') }
    finally { setBusy('') }
  }
  const settings = { efforts: selectedEfforts, model, preamble, samples }
  const prepareTask = () => perform(async () => {
    await flow.prepareTask({ existing: published.find((item) => item.id === existingId), title, prompt, workspaceId: selectedWorkspace, baseSha, command, expectation })
    setStep(1)
  })
  const review = () => perform(async () => { setPreflight(await flow.review(settings)); setStep(2) })
  const start = () => perform(async () => { await flow.start(settings) })
  const changeSettings = () => setPreflight(null)

  return <>
    <div className="evals-page-header"><div><span className="eyebrow">Guided setup</span><h1>New evaluation</h1><p>Add a task, choose reasoning levels, and compare the results.</p></div></div>
    <ol className="eval-guide-steps" aria-label="Evaluation progress">{['Add task', 'Choose reasoning', 'Review & run'].map((label, index) => <li key={label} aria-current={step === index ? 'step' : undefined} className={step === index ? 'current' : step > index ? 'complete' : ''}><span>{index + 1}</span>{label}</li>)}</ol>
    <div className="case-create-card eval-guide-card" aria-busy={!!busy}>
      {!live && <p className="eval-guide-note">Connect to the backend to set up an evaluation.</p>}
      {error && <div className="evals-error" role="alert">{error}</div>}
      <fieldset disabled={!!busy || !live}>
        {step === 0 && <>
          <h2>What should Codex do?</h2>
          <p className="eval-guide-note">Each reasoning level will run the same task from the same Git commit.</p>
          {!locked && !displayTask && <label>Task<select value={existingId} onChange={(event) => setExistingId(Number(event.target.value))}><option value={0}>Add a new task</option>{published.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
          {locked ? <p className="eval-guide-note">{displayTask?.title} is validated and ready. Continue to choose reasoning.</p> : existingId ? <p className="eval-guide-note">This published task already has a test command and a pinned base commit.</p> : <>
            <label>Task name<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} placeholder="Fix parser regression" /></label>
            <label>Workspace<select disabled={!!displayTask} value={selectedWorkspace} onChange={(event) => setWorkspaceId(Number(event.target.value))}><option value={0} disabled>Select a workspace</option>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            {!workspaces.length && <p className="eval-guide-note">Use Add repository above to import a GitHub repository, or add a local workspace in Chat mode.</p>}
            <label>Task prompt<textarea rows={5} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe the change Codex should make and what success looks like." /></label>
            <label>Test command<input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="e.g. pytest -q tests/test_parser.py" /><span className="eval-guide-note">Runs after Codex finishes to determine whether it succeeded. Use a command with plain arguments.</span></label>
            {/["'|;&<>`$]/.test(command) && <p role="alert" className="preflight-warning">Use plain arguments here. For complex verification, put the check in a script and enter its command.</p>}
            {!!baseSha.trim() && !/^[a-f\d]{40}$/i.test(baseSha.trim()) && <p role="alert" className="preflight-warning">Enter a full 40-character Git commit SHA, or leave it blank.</p>}
            <label>Expected test result before Codex runs<select value={expectation} onChange={(event) => setExpectation(event.target.value)}><option value="required_scorer_fails">Fail — Codex needs to fix it</option><option value="required_scorer_passes">Pass — Codex should keep it passing</option><option value="none">Either — do not require a base result</option></select></label>
            <details><summary>Advanced task settings</summary><label>Base commit<input value={baseSha} onChange={(event) => setBaseSha(event.target.value)} placeholder="Leave blank to use the current HEAD commit" /></label><p className="eval-guide-note">The task uses committed files. For hidden tests or custom scorers, use Tasks in the sidebar.</p></details>
          </>}
          <div className="case-create-actions"><button className="primary-action" disabled={!locked && !existingId && (!title.trim() || !prompt.trim() || !command.trim() || !selectedWorkspace || /["'|;&<>`$]/.test(command) || (!!baseSha.trim() && !/^[a-f\d]{40}$/i.test(baseSha.trim())))} onClick={() => void prepareTask()}>Validate task & continue</button></div>
        </>}
        {step === 1 && <>
          <h2>Choose reasoning levels</h2><p className="eval-guide-note">Select one level to evaluate, or two to compare. Both use the same model, instructions, and task.</p>
          <div className="eval-guide-efforts">{efforts.map((effort) => <label key={effort} className={selectedEfforts.includes(effort) ? 'selected' : ''}><input type="checkbox" checked={selectedEfforts.includes(effort)} disabled={!selectedEfforts.includes(effort) && selectedEfforts.length === 2} onChange={() => { changeSettings(); setSelectedEfforts((current) => current.includes(effort) ? current.filter((item) => item !== effort) : [...current, effort]) }} />{effortLabel(effort)}</label>)}</div>
          <label>Model<input value={model} onChange={(event) => { changeSettings(); setModel(event.target.value) }} placeholder="Leave blank to use the default model" /></label>
          <label>Runs per reasoning level<input type="number" min={1} max={10} value={samples} onChange={(event) => { setPreflight(null); setSamples(Number(event.target.value)) }} /><span className="eval-guide-note">Repeat runs to account for variation. More runs take more time.</span></label>
          <details><summary>Additional instructions</summary><label>Instructions for every run<textarea rows={3} value={preamble} onChange={(event) => { changeSettings(); setPreamble(event.target.value) }} placeholder="Optional instructions shared by both reasoning levels" /></label></details>
          <div className="case-create-actions"><button className="secondary-action" onClick={() => setStep(0)}>Back</button><button className="primary-action" disabled={!selectedEfforts.length || !Number.isInteger(samples) || samples < 1 || samples > 10} onClick={() => void review()}>Review evaluation</button></div>
        </>}
        {step === 2 && preflight && <>
          <h2>Ready to run?</h2><dl className="eval-guide-summary"><div><dt>Task</dt><dd>{displayTask?.title}</dd></div><div><dt>Model</dt><dd>{model.trim() || 'Default model'}</dd></div><div><dt>Reasoning</dt><dd>{selectedEfforts.map(effortLabel).join(' vs ')}</dd></div><div><dt>Total runs</dt><dd>{preflight.attempt_count} ({preflight.samples_per_case} per level)</dd></div><div><dt>Workspace</dt><dd>{workspaces.find((item) => item.id === displayTask?.latest_revision?.workspace_id)?.name}</dd></div></dl>
          <p className="eval-guide-note">Runs execute in disposable Git worktrees with workspace write access and network disabled. The task and reasoning settings have been saved for repeatable runs.</p>
          {preflight.warnings.map((warning) => <p className="preflight-warning" key={warning}>{warning}</p>)}
          {!!preflight.invalid_case_revision_ids.length && <p role="alert" className="preflight-warning">This task cannot run. Open Tasks to resolve its validation issues.</p>}
          <div className="case-create-actions"><button className="secondary-action" disabled={hasExperiment} onClick={() => setStep(1)}>Back</button><button className="primary-action" disabled={!!preflight.invalid_case_revision_ids.length} onClick={() => void start()}>{hasExperiment ? 'Retry start' : `Run evaluation · ${preflight.attempt_count} runs`}</button></div>
        </>}
      </fieldset>
      {busy && <p className="eval-guide-note" role="status">{busy}</p>}
    </div>
  </>
}
