import { useEffect, useState } from 'react'
import { Beaker, FlaskConical, Layers3, Plus, Settings2 } from 'lucide-react'
import { rpcClient } from './runtime'
import type { EvalAttemptDetail, EvalAttemptEvent, EvalCase, EvalConfig, EvalExperiment, EvalExperimentEvent, EvalPreflight, EvalScorerOutput, EvalStep, EvalSuite, RunDiff, Workspace } from './runtime'
import { RunDiffView } from './RunDiffView'
import { EvalResultsView } from './EvalResultsView'
import { EvalConfigDiff } from './EvalConfigDiff'

type Section = 'experiments' | 'cases' | 'suites' | 'configurations'

type Props = {
  live: boolean
  demo: boolean
  workspaces: Workspace[]
}

const navigation: { id: Section; label: string; icon: typeof Beaker }[] = [
  { id: 'experiments', label: 'Experiments', icon: Beaker },
  { id: 'cases', label: 'Cases', icon: FlaskConical },
  { id: 'suites', label: 'Suites', icon: Layers3 },
  { id: 'configurations', label: 'Configurations', icon: Settings2 },
]

export function EvalsMode({ live, demo, workspaces }: Props) {
  const [section, setSection] = useState<Section>('experiments')
  const [cases, setCases] = useState<EvalCase[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [workspaceId, setWorkspaceId] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingCaseId, setEditingCaseId] = useState<number | null>(null)
  const [baseSha, setBaseSha] = useState('')
  const [draftPrompt, setDraftPrompt] = useState('')
  const [verifierCommand, setVerifierCommand] = useState('')
  const [heldOutPath, setHeldOutPath] = useState('')
  const [heldOutContent, setHeldOutContent] = useState('')
  const [clearHeldOut, setClearHeldOut] = useState(false)
  const [baseExpectation, setBaseExpectation] = useState('required_scorer_fails')
  const [suites, setSuites] = useState<EvalSuite[]>([])
  const [configs, setConfigs] = useState<EvalConfig[]>([])
  const [newSuiteName, setNewSuiteName] = useState('')
  const [newConfigName, setNewConfigName] = useState('')
  const [configModel, setConfigModel] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('medium')
  const [configPreamble, setConfigPreamble] = useState('')
  const [configSandbox, setConfigSandbox] = useState('workspace-write')
  const [configCaptureWorkspace, setConfigCaptureWorkspace] = useState(0)
  const [experiments, setExperiments] = useState<EvalExperiment[]>([])
  const [experimentName, setExperimentName] = useState('')
  const [suiteVersionId, setSuiteVersionId] = useState(0)
  const [configAId, setConfigAId] = useState(0)
  const [configBId, setConfigBId] = useState(0)
  const [samples, setSamples] = useState(1)
  const [preflight, setPreflight] = useState<EvalPreflight | null>(null)
  const [selectedExperiment, setSelectedExperiment] = useState<EvalExperiment | null>(null)
  const [selectedAttempt, setSelectedAttempt] = useState<EvalAttemptDetail | null>(null)
  const [attemptSteps, setAttemptSteps] = useState<EvalStep[]>([])
  const [attemptEvents, setAttemptEvents] = useState<EvalAttemptEvent[]>([])
  const [evalDiff, setEvalDiff] = useState<RunDiff | null>(null)
  const [scorerOutput, setScorerOutput] = useState<EvalScorerOutput | null>(null)
  const [scorerOutputError, setScorerOutputError] = useState<{ artifactId: number; message: string } | null>(null)
  const [scorerOutputLoading, setScorerOutputLoading] = useState(false)
  const selectedWorkspaceId = workspaceId || workspaces[0]?.id || 0
  const runningExperimentIds = experiments.filter((item) => item.status === 'running').map((item) => item.id)
  const runningExperimentKey = runningExperimentIds.join(',')

  useEffect(() => {
    if (!live) return
    let cancelled = false
    let refreshing = false
    const refresh = () => {
      if (cancelled || refreshing) return
      refreshing = true
      void Promise.all([
      rpcClient.request<EvalCase[]>('eval.case.list'),
      rpcClient.request<EvalSuite[]>('eval.suite.list'),
      rpcClient.request<EvalConfig[]>('eval.config.list'),
      rpcClient.request<EvalExperiment[]>('eval.experiment.list'),
    ]).then(([loadedCases, loadedSuites, loadedConfigs, loadedExperiments]) => {
      if (!cancelled) { setCases(loadedCases); setSuites(loadedSuites); setConfigs(loadedConfigs); setExperiments(loadedExperiments); setError(null) }
    }).catch((requestError) => {
      if (!cancelled) setError(requestError instanceof Error ? requestError.message : 'Could not load eval cases.')
    }).finally(() => {
      refreshing = false
    })
    }
    refresh()
    // Subscriptions cover known running experiments; discover API-created records too.
    const timer = demo ? undefined : window.setInterval(refresh, 10_000)
    if (!demo) window.addEventListener('focus', refresh)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [live, demo])

  useEffect(() => {
    if (!live || demo || !runningExperimentIds.length) return
    const refreshExperiment = (event: EvalExperimentEvent) => {
      void rpcClient.request<EvalExperiment>('eval.experiment.get', { experiment_id: event.experiment_id }).then((updated) => {
        setExperiments((current) => current.map((item) => item.id === updated.id ? updated : item))
        setSelectedExperiment((current) => current?.id === updated.id ? updated : current)
      }).catch(() => undefined)
    }
    rpcClient.onExperimentEvent(refreshExperiment)
    for (const experimentId of runningExperimentIds) {
      void rpcClient.request('eval.experiment.subscribe', { experiment_id: experimentId }).catch(() => undefined)
    }
    return () => {
      rpcClient.onExperimentEvent(null)
      for (const experimentId of runningExperimentIds) {
        void rpcClient.request('eval.experiment.unsubscribe', { experiment_id: experimentId }).catch(() => undefined)
      }
    }
  // The joined key changes only when the subscription set changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, demo, runningExperimentKey])

  const createCase = async () => {
    if (!title.trim() || !prompt.trim() || !selectedWorkspaceId) return
    setLoading(true)
    try {
      const created = await rpcClient.request<EvalCase>('eval.case.create', {
        title: title.trim(),
        prompt: prompt.trim(),
        workspace_id: selectedWorkspaceId,
      })
      setCases((current) => [created, ...current])
      setTitle(''); setPrompt(''); setShowCreate(false); setError(null)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not create the case.')
    } finally { setLoading(false) }
  }

  const replaceCase = (updated: EvalCase) => setCases((current) => current.map((item) => item.id === updated.id ? updated : item))
  const editCase = (evalCase: EvalCase) => {
    setEditingCaseId(evalCase.id); setBaseSha(evalCase.latest_revision.base_sha ?? '')
    setDraftPrompt(evalCase.latest_revision.prompt)
    setHeldOutPath(''); setHeldOutContent(''); setClearHeldOut(false)
    setBaseExpectation(typeof evalCase.latest_revision.path_policy.base_expectation === 'string' ? evalCase.latest_revision.path_policy.base_expectation : 'required_scorer_fails')
    const command = evalCase.latest_revision.scorer_spec.find((scorer) => scorer.type === 'command')
    const candidates = evalCase.latest_revision.validation_details.candidate_verifier_commands
    setVerifierCommand(Array.isArray(command?.argv) ? command.argv.join(' ') : Array.isArray(candidates) && typeof candidates[0] === 'string' ? candidates[0] : '')
  }
  const saveDraft = async (evalCase: EvalCase) => {
    const argv = verifierCommand.trim().split(/\s+/).filter(Boolean); setLoading(true)
    try {
      const verifierUpdate = clearHeldOut ? { verifier_files: [] } : heldOutPath.trim() ? { verifier_files: [{ path: heldOutPath.trim(), content: heldOutContent }] } : {}
      const existing = evalCase.latest_revision.scorer_spec
      const commandIndex = existing.findIndex((scorer) => scorer.type === 'command')
      const original = commandIndex < 0 ? '' : (existing[commandIndex].argv as string[]).join(' ')
      // Prompt-only edits must preserve every scorer and its original options.
      const scorerUpdate = verifierCommand.trim() === original ? {} : { scorer_spec: commandIndex < 0
        ? [...existing, ...(argv.length ? [{ type: 'command', key: 'verifier', argv }] : [])]
        : existing.flatMap((scorer, index) => index !== commandIndex ? [scorer] : argv.length ? [{ ...scorer, argv }] : []) }
      replaceCase(await rpcClient.request<EvalCase>('eval.case.update_draft', { case_id: evalCase.id, revision_id: evalCase.latest_revision.id, prompt: draftPrompt.trim(), base_sha: baseSha.trim() || null, ...scorerUpdate, path_policy: { ...evalCase.latest_revision.path_policy, base_expectation: baseExpectation }, ...verifierUpdate }))
      setHeldOutPath(''); setHeldOutContent(''); setClearHeldOut(false); setError(null)
    }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not save the draft.') }
    finally { setLoading(false) }
  }
  const caseAction = async (evalCase: EvalCase, action: 'validate' | 'publish') => {
    setLoading(true)
    try { replaceCase(await rpcClient.request<EvalCase>(`eval.case.${action}`, { case_id: evalCase.id, revision_id: evalCase.latest_revision.id })); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : `Could not ${action} the case.`) }
    finally { setLoading(false) }
  }
  const reviseCase = async (evalCase: EvalCase) => {
    setLoading(true)
    try {
      const updated = await rpcClient.request<EvalCase>('eval.case.revise', { case_id: evalCase.id, revision_id: evalCase.latest_revision.id })
      replaceCase(updated); editCase(updated); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not create a draft revision.') }
    finally { setLoading(false) }
  }
  const createSuite = async () => {
    if (!newSuiteName.trim()) return
    setLoading(true)
    try {
      let suite = await rpcClient.request<EvalSuite>('eval.suite.create', { name: newSuiteName.trim() })
      const revisionIds = cases.filter((item) => item.latest_revision.status === 'published').map((item) => item.latest_revision.id)
      if (revisionIds.length) suite = await rpcClient.request<EvalSuite>('eval.suite.update_draft', { suite_id: suite.id, version_id: suite.latest_version.id, case_revision_ids: revisionIds })
      setSuites((current) => [suite, ...current]); setNewSuiteName(''); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not create the suite.') }
    finally { setLoading(false) }
  }
  const freezeSuite = async (suite: EvalSuite) => {
    setLoading(true)
    try { const frozen = await rpcClient.request<EvalSuite>('eval.suite.freeze', { suite_id: suite.id, version_id: suite.latest_version.id }); setSuites((current) => current.map((item) => item.id === frozen.id ? frozen : item)); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not freeze the suite.') }
    finally { setLoading(false) }
  }
  const captureConfig = async () => {
    if (!newConfigName.trim()) return
    setLoading(true)
    try { const config = await rpcClient.request<EvalConfig>('eval.config.capture', { name: newConfigName.trim(), workspace_id: configCaptureWorkspace || undefined, model: configModel.trim() || null, reasoning_effort: reasoningEffort, instruction_preamble: configPreamble, sandbox_policy: { mode: configSandbox, network: false } }); setConfigs((current) => [config, ...current]); setNewConfigName(''); setConfigModel(''); setConfigPreamble(''); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not capture the configuration.') }
    finally { setLoading(false) }
  }
  const experimentPlan = () => {
    const frozenSuites = suites.filter((suite) => suite.latest_version.status === 'frozen')
    const selectedSuite = suiteVersionId || frozenSuites[0]?.latest_version.id || 0
    const selectedA = configAId || configs[0]?.snapshot.id || 0
    const selectedB = configBId || configs[1]?.snapshot.id || 0
    return { name: experimentName.trim(), suite_version_id: selectedSuite, config_snapshot_ids: [selectedA, selectedB].filter((id, index, values) => id && values.indexOf(id) === index), samples_per_case: samples, concurrency: 1, timeout_seconds: 1800 }
  }
  const reviewExperiment = async () => {
    setLoading(true)
    try { setPreflight(await rpcClient.request<EvalPreflight>('eval.experiment.preflight', experimentPlan())); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not run experiment preflight.') }
    finally { setLoading(false) }
  }
  const createExperiment = async () => {
    setLoading(true)
    try { const created = await rpcClient.request<EvalExperiment>('eval.experiment.create', experimentPlan()); setExperiments((current) => [created, ...current]); setPreflight(null); setExperimentName(''); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not create the experiment.') }
    finally { setLoading(false) }
  }
  const experimentAction = async (experiment: EvalExperiment, action: 'start' | 'cancel' | 'resume') => {
    setLoading(true)
    try {
      await rpcClient.request(`eval.experiment.${action}`, { experiment_id: experiment.id })
      setExperiments(await rpcClient.request<EvalExperiment[]>('eval.experiment.list'))
      setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : `Could not ${action} the experiment.`) }
    finally { setLoading(false) }
  }
  const openExperiment = async (experiment: EvalExperiment) => {
    setLoading(true)
    try { setSelectedExperiment(await rpcClient.request<EvalExperiment>('eval.experiment.get', { experiment_id: experiment.id })); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not load experiment results.') }
    finally { setLoading(false) }
  }
  const openAttempt = async (attemptId: number) => {
    setLoading(true)
    setScorerOutput(null)
    setScorerOutputError(null)
    try { const [detail, steps, events] = await Promise.all([rpcClient.request<EvalAttemptDetail>('eval.attempt.get', { attempt_id: attemptId }), rpcClient.request<EvalStep[]>('eval.attempt.steps', { attempt_id: attemptId }), rpcClient.request<EvalAttemptEvent[]>('eval.attempt.events', { attempt_id: attemptId })]); setSelectedAttempt(detail); setAttemptSteps(steps); setAttemptEvents(events); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not load attempt evidence.') }
    finally { setLoading(false) }
  }
  const retryAttempt = async (attempt: EvalAttemptDetail) => {
    setLoading(true)
    try {
      await rpcClient.request('eval.attempt.retry', { attempt_id: attempt.id })
      setSelectedAttempt(null)
      setExperiments(await rpcClient.request<EvalExperiment[]>('eval.experiment.list'))
      setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not retry the attempt.') }
    finally { setLoading(false) }
  }
  const openScorerOutput = async (attemptId: number, artifactId: number) => {
    setScorerOutputLoading(true)
    setScorerOutputError(null)
    try {
      setScorerOutput(await rpcClient.request<EvalScorerOutput>('eval.attempt.artifact', { attempt_id: attemptId, artifact_id: artifactId }))
    } catch (requestError) { setScorerOutputError({ artifactId, message: requestError instanceof Error ? requestError.message : 'Could not read scorer output.' }) }
    finally { setScorerOutputLoading(false) }
  }
  const loadMoreScorerOutput = async () => {
    if (!scorerOutput || !scorerOutput.has_more || scorerOutputLoading) return
    setScorerOutputLoading(true)
    try {
      const next = await rpcClient.request<EvalScorerOutput>('eval.attempt.artifact', { attempt_id: scorerOutput.attempt_id, artifact_id: scorerOutput.artifact_id, offset: scorerOutput.next_offset })
      setScorerOutput((current) => current?.artifact_id === next.artifact_id ? { ...next, stdout: current.stdout + next.stdout, stderr: current.stderr + next.stderr } : current)
    } catch (requestError) { setScorerOutputError({ artifactId: scorerOutput.artifact_id, message: requestError instanceof Error ? requestError.message : 'Could not load more output.' }) }
    finally { setScorerOutputLoading(false) }
  }

  return <div className="evals-layout">
    <aside className="evals-sidebar">
      <div className="evals-sidebar-heading"><span className="eyebrow">Evaluation</span><strong>Measure Codex</strong></div>
      <nav aria-label="Evals navigation">
        {navigation.map(({ id, label, icon: Icon }) => <button key={id} className={section === id ? 'selected' : ''} onClick={() => setSection(id)}><Icon size={15} /><span>{label}</span></button>)}
      </nav>
      <p>Runs stay local and execute in disposable Git worktrees.</p>
    </aside>

    <section className="evals-main">
      {demo && <p className="evals-demo-notice">Synthetic Evals demo · read-only examples, not measured Codex results. Open the experiment to explore comparison filters and attempt evidence.</p>}
      {section === 'experiments' && <>
        <div className="evals-page-header"><div><span className="eyebrow">Evals mode</span><h1>Experiments</h1><p>Compare Codex configurations against the same versioned tasks.</p></div></div>
        {error && <div className="evals-error">{error}</div>}
{!demo && (<div className="experiment-launch"><div className="experiment-fields"><input value={experimentName} onChange={(event) => { setExperimentName(event.target.value); setPreflight(null) }} placeholder="Experiment name (optional)" /><select value={suiteVersionId} onChange={(event) => { setSuiteVersionId(Number(event.target.value)); setPreflight(null) }}><option value={0}>Select frozen suite</option>{suites.filter((suite) => suite.latest_version.status === 'frozen').map((suite) => <option key={suite.latest_version.id} value={suite.latest_version.id}>{suite.name} v{suite.latest_version.version}</option>)}</select><select value={configAId} onChange={(event) => { setConfigAId(Number(event.target.value)); setPreflight(null) }}><option value={0}>Config A</option>{configs.map((config) => <option key={config.snapshot.id} value={config.snapshot.id}>{config.name}</option>)}</select><select value={configBId} onChange={(event) => { setConfigBId(Number(event.target.value)); setPreflight(null) }}><option value={0}>Config B (optional)</option>{configs.map((config) => <option key={config.snapshot.id} value={config.snapshot.id}>{config.name}</option>)}</select><label>Samples<input type="number" min={1} max={10} value={samples} onChange={(event) => { setSamples(Number(event.target.value)); setPreflight(null) }} /></label></div>{preflight ? <div className="preflight-card"><div><span className="eyebrow">Preflight</span><strong>{preflight.attempt_count} attempts</strong><p>{preflight.case_count} cases × {preflight.config_count} configurations × {preflight.samples_per_case} samples</p></div><dl><div><dt>Isolation</dt><dd>{preflight.isolation}</dd></div><div><dt>Network</dt><dd>{preflight.network_enabled ? 'Enabled' : 'Disabled'}</dd></div><div><dt>Differences</dt><dd>{preflight.configuration_differences.join(', ') || 'Single configuration'}</dd></div></dl>{preflight.warnings.map((warning) => <p className="preflight-warning" key={warning}>{warning}</p>)}<button className="primary-action" disabled={loading || !!preflight.invalid_case_revision_ids.length} onClick={() => void createExperiment()}>Create {preflight.attempt_count} attempts</button></div> : <button className="primary-action launch-review" disabled={loading || !suites.some((suite) => suite.latest_version.status === 'frozen') || !configs.length} onClick={() => void reviewExperiment()}>Review preflight</button>}</div>)}
        <div className="eval-object-list">{experiments.map((experiment) => <article className="eval-object-card" key={experiment.id}><div><span className={`case-status ${experiment.status === 'completed' ? 'published' : ''}`}>{experiment.status}</span><h2>{experiment.name}</h2><p>{experiment.attempt_count} attempts · {experiment.attempt_status_counts.completed ?? 0} completed · {experiment.attempt_status_counts.running ?? 0} running · {experiment.attempt_status_counts.queued ?? 0} queued</p></div><div className="experiment-actions">{experiment.status === 'ready' && <button className="primary-action" disabled={loading} onClick={() => void experimentAction(experiment, 'start')}>Start experiment</button>}{experiment.status === 'running' && <button className="secondary-action" disabled={loading} onClick={() => void experimentAction(experiment, 'cancel')}>Cancel</button>}{experiment.status === 'failed' && (experiment.attempt_status_counts.interrupted ?? 0) > 0 && <button className="primary-action" disabled={loading} onClick={() => void experimentAction(experiment, 'resume')}>Resume interrupted</button>}{experiment.status !== 'ready' && <button className="secondary-action" disabled={loading} onClick={() => void openExperiment(experiment)}>Open results</button>}</div></article>)}</div>
        {!experiments.length && <div className="evals-empty-state compact"><Beaker size={26} /><h2>No experiments yet</h2><p>Freeze a suite and capture at least one configuration to create a durable attempt plan.</p></div>}
        {selectedExperiment && <EvalResultsView key={selectedExperiment.id} experiment={selectedExperiment} onClose={() => setSelectedExperiment(null)} onAttempt={(id) => void openAttempt(id)} />}
      </>}

      {section === 'cases' && <>
        <div className="evals-page-header"><div><span className="eyebrow">Reusable tasks</span><h1>Cases</h1><p>Draft tasks become immutable once validated and published.</p></div><button className="primary-action" disabled={demo || !live || !workspaces.length} onClick={() => setShowCreate(true)}><Plus size={14} /> New case</button></div>
        {error && <div className="evals-error">{error}</div>}
        {showCreate && <div className="case-create-card">
          <div><span className="eyebrow">Draft case</span><h2>Define the task</h2></div>
          <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Fix parser regression" autoFocus /></label>
          <label>Workspace<select value={selectedWorkspaceId} onChange={(event) => setWorkspaceId(Number(event.target.value))}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label>
          <label>Prompt<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe exactly what Codex should accomplish…" rows={5} /></label>
          <div className="case-create-actions"><button className="secondary-action" onClick={() => setShowCreate(false)}>Cancel</button><button className="primary-action" disabled={loading || !title.trim() || !prompt.trim() || !selectedWorkspaceId} onClick={() => void createCase()}>{loading ? 'Creating…' : 'Create draft'}</button></div>
        </div>}
        {!showCreate && cases.length === 0 && <div className="evals-empty-state compact"><FlaskConical size={24} /><h2>No cases yet</h2><p>Create a draft with a workspace and task prompt. Validation and deterministic scorers come before publishing.</p></div>}
        <div className="case-list">{cases.map((evalCase) => <article className={`case-card ${editingCaseId === evalCase.id ? 'editing' : ''}`} key={evalCase.id}><div className="case-card-summary"><div><span className={`case-status ${evalCase.latest_revision.status}`}>{evalCase.latest_revision.status}</span><h2>{evalCase.title}</h2><p>{evalCase.latest_revision.prompt}</p></div><dl><div><dt>Workspace</dt><dd>{workspaces.find((workspace) => workspace.id === evalCase.latest_revision.workspace_id)?.name ?? `#${evalCase.latest_revision.workspace_id}`}</dd></div><div><dt>Validation</dt><dd>{evalCase.latest_revision.validation_status.replace('_', ' ')}</dd></div><div><dt>Revision</dt><dd>v{evalCase.latest_revision.revision}</dd></div></dl>{evalCase.latest_revision.status === 'draft' && <button className="secondary-action" onClick={() => editCase(evalCase)}>Configure</button>}{evalCase.latest_revision.status === 'published' && <button className="secondary-action" disabled={demo || loading} onClick={() => void reviseCase(evalCase)}>New draft revision</button>}</div>{editingCaseId === evalCase.id && <div className="case-editor"><label>Task prompt<textarea value={draftPrompt} onChange={(event) => setDraftPrompt(event.target.value)} rows={5} /></label><label>Base commit SHA<input value={baseSha} onChange={(event) => setBaseSha(event.target.value)} placeholder="Full 40-character commit SHA" /></label><label>Verifier command<input value={verifierCommand} onChange={(event) => setVerifierCommand(event.target.value)} placeholder="pytest -q" /></label><label>Base-state expectation<select value={baseExpectation} onChange={(event) => setBaseExpectation(event.target.value)}><option value="required_scorer_fails">At least one required scorer fails</option><option value="required_scorer_passes">All required scorers pass</option><option value="none">No base result requirement</option></select></label><label>Held-out verifier path<input value={heldOutPath} onChange={(event) => { setHeldOutPath(event.target.value); setClearHeldOut(false) }} placeholder="tests/hidden_verifier.py" /></label><label>Held-out verifier file content<textarea value={heldOutContent} onChange={(event) => setHeldOutContent(event.target.value)} rows={5} placeholder="Installed for validation and after the agent run" /></label>{evalCase.latest_revision.verifier_artifact_id && <label className="held-out-clear"><input type="checkbox" checked={clearHeldOut} onChange={(event) => setClearHeldOut(event.target.checked)} /> Remove existing held-out bundle</label>}{evalCase.latest_revision.verifier_artifact_id && !clearHeldOut && <p>Held-out verifier bundle attached. Enter a new path and content to replace it.</p>}{Array.isArray(evalCase.latest_revision.validation_details.problems) && evalCase.latest_revision.validation_details.problems.length > 0 && <ul>{(evalCase.latest_revision.validation_details.problems as string[]).map((problem) => <li key={problem}>{problem}</li>)}</ul>}<div className="case-create-actions"><button className="secondary-action" onClick={() => setEditingCaseId(null)}>Close</button><button className="secondary-action" disabled={demo || loading} onClick={() => void saveDraft(evalCase)}>Save</button><button className="secondary-action" disabled={loading || !evalCase.latest_revision.scorer_spec.length} onClick={() => void caseAction(evalCase, 'validate')}>Validate</button><button className="primary-action" disabled={loading || evalCase.latest_revision.validation_status !== 'valid'} onClick={() => void caseAction(evalCase, 'publish')}>Publish revision</button></div></div>}</article>)}</div>
      </>}

      {section === 'suites' && <><div className="evals-page-header"><div><span className="eyebrow">Versioned collections</span><h1>Suites</h1><p>Freeze ordered collections of published cases.</p></div></div>{error && <div className="evals-error">{error}</div>}{!demo && <div className="eval-create-row"><input value={newSuiteName} onChange={(event) => setNewSuiteName(event.target.value)} placeholder="Regression suite" /><button className="primary-action" disabled={loading || !newSuiteName.trim()} onClick={() => void createSuite()}><Plus size={14} /> Create suite</button></div>}<div className="eval-object-list">{suites.map((suite) => <article className="eval-object-card" key={suite.id}><div><span className={`case-status ${suite.latest_version.status === 'frozen' ? 'published' : ''}`}>{suite.latest_version.status}</span><h2>{suite.name}</h2><p>{suite.latest_version.cases.length} published case{suite.latest_version.cases.length === 1 ? '' : 's'} · version {suite.latest_version.version}</p></div>{suite.latest_version.status === 'draft' && <button className="primary-action" disabled={loading || !suite.latest_version.cases.length} onClick={() => void freezeSuite(suite)}>Freeze version</button>}</article>)}</div>{!suites.length && <div className="evals-empty-state compact"><Layers3 size={24} /><h2>No suites yet</h2><p>Publish cases first, then create a frozen collection for repeatable experiments.</p></div>}</>}

      {section === 'configurations' && <><div className="evals-page-header"><div><span className="eyebrow">Controlled inputs</span><h1>Configurations</h1><p>Capture immutable, hashed Codex setups.</p></div></div>{error && <div className="evals-error">{error}</div>}{!demo && <div className="eval-config-form"><select aria-label="Instruction capture workspace" value={configCaptureWorkspace} onChange={(event) => setConfigCaptureWorkspace(Number(event.target.value))}><option value={0}>No workspace · skip file capture</option>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name} · capture instructions</option>)}</select><input value={newConfigName} onChange={(event) => setNewConfigName(event.target.value)} placeholder="Configuration name" /><input value={configModel} onChange={(event) => setConfigModel(event.target.value)} placeholder="Model override (optional)" /><select value={reasoningEffort} onChange={(event) => setReasoningEffort(event.target.value)}><option value="low">Low reasoning</option><option value="medium">Medium reasoning</option><option value="high">High reasoning</option><option value="xhigh">Extra-high reasoning</option></select><select aria-label="Sandbox policy" value={configSandbox} onChange={(event) => setConfigSandbox(event.target.value)}><option value="workspace-write">Workspace write · network disabled</option><option value="read-only">Read only · network disabled</option></select><textarea className="config-preamble" aria-label="Instruction preamble" value={configPreamble} onChange={(event) => setConfigPreamble(event.target.value)} placeholder="Optional instruction preamble applied before every task (do not include secrets)" /><button className="primary-action" disabled={loading || !newConfigName.trim()} onClick={() => void captureConfig()}><Plus size={14} /> Capture</button></div>}<EvalConfigDiff configs={configs} /><div className="eval-object-list">{configs.map((config) => <article className="eval-object-card" key={config.id}><div><span className="case-status published">snapshot</span><h2>{config.name}</h2><p>{config.snapshot.model ?? 'Default model'} · {config.snapshot.reasoning_effort ?? 'default'} reasoning · {config.snapshot.content_hash.slice(0, 10)}</p><p>CLI: {config.snapshot.cli_version ?? 'unavailable'}</p><details><summary>Captured instruction chain ({config.snapshot.instructions.filter((item) => item.kind === 'file').length} files)</summary>{config.snapshot.instructions.filter((item) => item.kind === 'file').map((item, index) => <div key={index}><p>{index + 1}. {String(item.path)} · observed{item.truncated ? ' · truncated' : ''}{item.redacted ? ' · redacted' : ''}</p><pre className="captured-instruction">{String(item.content ?? '')}</pre></div>)}</details><p>{String(config.snapshot.sandbox_policy.mode ?? 'workspace-write')} · network disabled</p>{config.snapshot.instructions.filter((item) => item.kind === 'preamble').map((item, index) => <p key={index}>Preamble: {String(item.content)}</p>)}{config.snapshot.reproducibility_warnings?.map((warning) => <p className="config-warning" key={warning}>{warning}</p>)}</div></article>)}</div>{!configs.length && <div className="evals-empty-state compact"><Settings2 size={24} /><h2>No configurations yet</h2><p>Capture the controlled model, reasoning, and sandbox inputs used by an experiment.</p></div>}</>}
    </section>
    {selectedAttempt && <div className="modal-backdrop attempt-backdrop" onClick={() => setSelectedAttempt(null)}>
      <section className="attempt-modal" onClick={(event) => event.stopPropagation()}>
        <div className="attempt-modal-header"><div><span className="eyebrow">Attempt evidence</span><h2>{selectedAttempt.case?.title ?? `Case revision #${selectedAttempt.case_revision_id}`}</h2><p>{selectedAttempt.configuration?.name ?? 'Configuration'} · sample {selectedAttempt.sample_index + 1}</p></div><div className="experiment-actions">{!demo && ['completed', 'cancelled', 'interrupted'].includes(selectedAttempt.status) && <button className="secondary-action" disabled={loading} onClick={() => void retryAttempt(selectedAttempt)}>Retry attempt</button>}<button className="icon-button" aria-label="Close attempt" onClick={() => setSelectedAttempt(null)}>×</button></div></div>
        <div className="attempt-overview"><span className={`attempt-outcome ${selectedAttempt.outcome}`}>{selectedAttempt.outcome ?? selectedAttempt.status}</span><dl><div><dt>Agent</dt><dd>{selectedAttempt.durations_ms.agent == null ? '—' : `${selectedAttempt.durations_ms.agent} ms`}</dd></div><div><dt>Setup</dt><dd>{selectedAttempt.durations_ms.setup == null ? '—' : `${selectedAttempt.durations_ms.setup} ms`}</dd></div><div><dt>Scoring</dt><dd>{selectedAttempt.durations_ms.scoring == null ? '—' : `${selectedAttempt.durations_ms.scoring} ms`}</dd></div></dl></div>
        <div className="attempt-evidence">
          <h3>Scorer evidence</h3>
          {selectedAttempt.scores.map((score) => <article key={score.key}>
            <div><span className={`score-dot ${score.passed ? 'pass' : 'fail'}`} /><strong>{score.key}</strong><b>{score.passed == null ? 'unavailable' : score.passed ? 'pass' : 'fail'}</b></div>
            <p>{score.summary}</p>
            {Object.keys(score.evidence).length > 0 && <pre>{JSON.stringify(score.evidence, null, 2)}</pre>}
            {score.artifact_id != null && <button className="secondary-action scorer-output-action" disabled={scorerOutputLoading} onClick={() => void openScorerOutput(selectedAttempt.id, score.artifact_id!)}>View full output</button>}
            {score.artifact_id != null && scorerOutput?.artifact_id === score.artifact_id && <div className="scorer-full-output">
              <h4>Complete scorer output</h4>
              <strong>stdout</strong><pre>{scorerOutput.stdout || '(empty)'}</pre>
              <strong>stderr</strong><pre>{scorerOutput.stderr || '(empty)'}</pre>
              {scorerOutput.has_more && <button className="secondary-action" disabled={scorerOutputLoading} onClick={() => void loadMoreScorerOutput()}>Load more output</button>}
              <small>{Math.min(scorerOutput.next_offset, scorerOutput.total_length).toLocaleString()} of {scorerOutput.total_length.toLocaleString()} characters loaded</small>
            </div>}
            {score.artifact_id != null && scorerOutputError?.artifactId === score.artifact_id && <p className="evals-error">{scorerOutputError.message}</p>}
          </article>)}
          {!selectedAttempt.scores.length && <p>No scorer evidence was produced.</p>}
          <h3>Final diff and artifacts</h3>
          <div className="attempt-artifact-row"><p>{selectedAttempt.diff ? `${selectedAttempt.diff.file_count} changed file${selectedAttempt.diff.file_count === 1 ? '' : 's'}` : 'No final diff is available.'} · {selectedAttempt.artifacts.length} artifact{selectedAttempt.artifacts.length === 1 ? '' : 's'}</p>{selectedAttempt.diff && <button className="secondary-action" onClick={() => setEvalDiff(selectedAttempt.diff)}>Inspect full diff</button>}</div>
          {selectedAttempt.artifacts.map((artifact) => <div className="artifact-row" key={artifact.id}><span>{artifact.type}</span><code>{artifact.byte_size.toLocaleString()} bytes · {artifact.sha256.slice(0, 12)}</code></div>)}
          <h3>Normalized steps</h3><div className="attempt-steps">{attemptSteps.map((step) => <article key={step.sequence}><span>{step.sequence}</span><div><strong>{step.title}</strong><p>{step.kind.replaceAll('_', ' ')} · {step.status}{step.duration_ms == null ? '' : ` · ${step.duration_ms} ms`}</p></div></article>)}{!attemptSteps.length && <p>No normalized execution steps are available.</p>}</div>
          <details className="attempt-raw-events"><summary>Raw event previews ({attemptEvents.length})</summary>{attemptEvents.map((event) => <article key={event.id}><strong>#{event.id} · {event.type}</strong><pre>{JSON.stringify(event.payload, null, 2)}</pre></article>)}</details>
        </div>
      </section>
    </div>}
    {evalDiff && <RunDiffView diff={evalDiff} readOnly onClose={() => setEvalDiff(null)} onDecision={async () => undefined} />}
  </div>
}
