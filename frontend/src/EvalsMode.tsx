import { useEffect, useState } from 'react'
import { Beaker, FlaskConical, Layers3, Plus, Settings2 } from 'lucide-react'
import { rpcClient } from './runtime'
import type { EvalAttemptDetail, EvalAttemptEvent, EvalCase, EvalConfig, EvalExperiment, EvalPreflight, EvalStep, EvalSuite, RunDiff, Workspace } from './runtime'
import { RunDiffView } from './RunDiffView'

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
  const [verifierCommand, setVerifierCommand] = useState('')
  const [suites, setSuites] = useState<EvalSuite[]>([])
  const [configs, setConfigs] = useState<EvalConfig[]>([])
  const [newSuiteName, setNewSuiteName] = useState('')
  const [newConfigName, setNewConfigName] = useState('')
  const [configModel, setConfigModel] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('medium')
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
  const selectedWorkspaceId = workspaceId || workspaces[0]?.id || 0

  useEffect(() => {
    if (!live || demo) return
    let cancelled = false
    void Promise.all([
      rpcClient.request<EvalCase[]>('eval.case.list'),
      rpcClient.request<EvalSuite[]>('eval.suite.list'),
      rpcClient.request<EvalConfig[]>('eval.config.list'),
      rpcClient.request<EvalExperiment[]>('eval.experiment.list'),
    ]).then(([loadedCases, loadedSuites, loadedConfigs, loadedExperiments]) => {
      if (!cancelled) { setCases(loadedCases); setSuites(loadedSuites); setConfigs(loadedConfigs); setExperiments(loadedExperiments); setError(null) }
    }).catch((requestError) => {
      if (!cancelled) setError(requestError instanceof Error ? requestError.message : 'Could not load eval cases.')
    })
    return () => { cancelled = true }
  }, [live, demo])

  useEffect(() => {
    if (!live || demo || !experiments.some((item) => item.status === 'running')) return
    const timer = window.setInterval(() => {
      void rpcClient.request<EvalExperiment[]>('eval.experiment.list').then(setExperiments).catch(() => undefined)
    }, 1200)
    return () => window.clearInterval(timer)
  }, [live, demo, experiments])

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
    const command = evalCase.latest_revision.scorer_spec.find((scorer) => scorer.type === 'command')
    const candidates = evalCase.latest_revision.validation_details.candidate_verifier_commands
    setVerifierCommand(Array.isArray(command?.argv) ? command.argv.join(' ') : Array.isArray(candidates) && typeof candidates[0] === 'string' ? candidates[0] : '')
  }
  const saveDraft = async (evalCase: EvalCase) => {
    const argv = verifierCommand.trim().split(/\s+/).filter(Boolean); setLoading(true)
    try { replaceCase(await rpcClient.request<EvalCase>('eval.case.update_draft', { case_id: evalCase.id, revision_id: evalCase.latest_revision.id, base_sha: baseSha.trim() || null, scorer_spec: argv.length ? [{ type: 'command', key: 'verifier', argv }] : [] })); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not save the draft.') }
    finally { setLoading(false) }
  }
  const caseAction = async (evalCase: EvalCase, action: 'validate' | 'publish') => {
    setLoading(true)
    try { replaceCase(await rpcClient.request<EvalCase>(`eval.case.${action}`, { case_id: evalCase.id, revision_id: evalCase.latest_revision.id })); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : `Could not ${action} the case.`) }
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
    try { const config = await rpcClient.request<EvalConfig>('eval.config.capture', { name: newConfigName.trim(), model: configModel.trim() || null, reasoning_effort: reasoningEffort, sandbox_policy: { mode: 'workspace-write', network: false } }); setConfigs((current) => [config, ...current]); setNewConfigName(''); setConfigModel(''); setError(null) }
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
  const experimentAction = async (experiment: EvalExperiment, action: 'start' | 'cancel') => {
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
    try { const [detail, steps, events] = await Promise.all([rpcClient.request<EvalAttemptDetail>('eval.attempt.get', { attempt_id: attemptId }), rpcClient.request<EvalStep[]>('eval.attempt.steps', { attempt_id: attemptId }), rpcClient.request<EvalAttemptEvent[]>('eval.attempt.events', { attempt_id: attemptId })]); setSelectedAttempt(detail); setAttemptSteps(steps); setAttemptEvents(events); setError(null) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not load attempt evidence.') }
    finally { setLoading(false) }
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
      {section === 'experiments' && <>
        <div className="evals-page-header"><div><span className="eyebrow">Evals mode</span><h1>Experiments</h1><p>Compare Codex configurations against the same versioned tasks.</p></div></div>
        {error && <div className="evals-error">{error}</div>}
        <div className="experiment-launch"><div className="experiment-fields"><input value={experimentName} onChange={(event) => { setExperimentName(event.target.value); setPreflight(null) }} placeholder="Experiment name (optional)" /><select value={suiteVersionId} onChange={(event) => { setSuiteVersionId(Number(event.target.value)); setPreflight(null) }}><option value={0}>Select frozen suite</option>{suites.filter((suite) => suite.latest_version.status === 'frozen').map((suite) => <option key={suite.latest_version.id} value={suite.latest_version.id}>{suite.name} v{suite.latest_version.version}</option>)}</select><select value={configAId} onChange={(event) => { setConfigAId(Number(event.target.value)); setPreflight(null) }}><option value={0}>Config A</option>{configs.map((config) => <option key={config.snapshot.id} value={config.snapshot.id}>{config.name}</option>)}</select><select value={configBId} onChange={(event) => { setConfigBId(Number(event.target.value)); setPreflight(null) }}><option value={0}>Config B (optional)</option>{configs.map((config) => <option key={config.snapshot.id} value={config.snapshot.id}>{config.name}</option>)}</select><label>Samples<input type="number" min={1} max={10} value={samples} onChange={(event) => { setSamples(Number(event.target.value)); setPreflight(null) }} /></label></div>{preflight ? <div className="preflight-card"><div><span className="eyebrow">Preflight</span><strong>{preflight.attempt_count} attempts</strong><p>{preflight.case_count} cases × {preflight.config_count} configurations × {preflight.samples_per_case} samples</p></div><dl><div><dt>Isolation</dt><dd>{preflight.isolation}</dd></div><div><dt>Network</dt><dd>{preflight.network_enabled ? 'Enabled' : 'Disabled'}</dd></div><div><dt>Differences</dt><dd>{preflight.configuration_differences.join(', ') || 'Single configuration'}</dd></div></dl>{preflight.warnings.map((warning) => <p className="preflight-warning" key={warning}>{warning}</p>)}<button className="primary-action" disabled={loading || !!preflight.invalid_case_revision_ids.length} onClick={() => void createExperiment()}>Create {preflight.attempt_count} attempts</button></div> : <button className="primary-action launch-review" disabled={loading || !suites.some((suite) => suite.latest_version.status === 'frozen') || !configs.length} onClick={() => void reviewExperiment()}>Review preflight</button>}</div>
        <div className="eval-object-list">{experiments.map((experiment) => <article className="eval-object-card" key={experiment.id}><div><span className={`case-status ${experiment.status === 'completed' ? 'published' : ''}`}>{experiment.status}</span><h2>{experiment.name}</h2><p>{experiment.attempt_count} attempts · {experiment.attempt_status_counts.completed ?? 0} completed · {experiment.attempt_status_counts.running ?? 0} running · {experiment.attempt_status_counts.queued ?? 0} queued</p></div><div className="experiment-actions">{experiment.status === 'ready' && <button className="primary-action" disabled={loading} onClick={() => void experimentAction(experiment, 'start')}>Start experiment</button>}{experiment.status === 'running' && <button className="secondary-action" disabled={loading} onClick={() => void experimentAction(experiment, 'cancel')}>Cancel</button>}{experiment.status !== 'ready' && <button className="secondary-action" disabled={loading} onClick={() => void openExperiment(experiment)}>Open results</button>}</div></article>)}</div>
        {!experiments.length && <div className="evals-empty-state compact"><Beaker size={26} /><h2>No experiments yet</h2><p>Freeze a suite and capture at least one configuration to create a durable attempt plan.</p></div>}
        {selectedExperiment && <section className="experiment-results"><div className="results-heading"><div><span className="eyebrow">Experiment results</span><h2>{selectedExperiment.name}</h2><p>{selectedExperiment.results.verdict.replaceAll('_', ' ')}</p></div><button className="secondary-action" onClick={() => setSelectedExperiment(null)}>Close</button></div><div className="result-metrics">{selectedExperiment.results.configurations.map((result, index) => <article key={result.config_snapshot_id}><span>{selectedExperiment.configurations[index]?.name ?? `Config ${index + 1}`}</span><strong>{result.pass_rate == null ? '—' : `${Math.round(result.pass_rate * 100)}%`}</strong><small>{result.passed} passed · {result.failed} failed · {result.infrastructure_errors} infra</small>{result.confidence_low != null && <small>95% CI {Math.round(result.confidence_low * 100)}–{Math.round((result.confidence_high ?? 0) * 100)}%</small>}</article>)}<article><span>Paired flips</span><strong>{selectedExperiment.results.paired.a_only_pass} / {selectedExperiment.results.paired.b_only_pass}</strong><small>A-only / B-only passes</small></article></div><div className="attempt-matrix">{selectedExperiment.attempts.map((attempt) => <button className={`attempt-cell ${attempt.outcome ?? attempt.status}`} key={attempt.id} onClick={() => void openAttempt(attempt.id)}><span>Case #{attempt.case_revision_id}</span><b>{selectedExperiment.configurations.find((item) => item.snapshot_id === attempt.config_snapshot_id)?.name ?? 'Config'}</b><small>{attempt.outcome ?? attempt.status}</small></button>)}</div></section>}
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
        <div className="case-list">{cases.map((evalCase) => <article className={`case-card ${editingCaseId === evalCase.id ? 'editing' : ''}`} key={evalCase.id}><div className="case-card-summary"><div><span className={`case-status ${evalCase.latest_revision.status}`}>{evalCase.latest_revision.status}</span><h2>{evalCase.title}</h2><p>{evalCase.latest_revision.prompt}</p></div><dl><div><dt>Workspace</dt><dd>{workspaces.find((workspace) => workspace.id === evalCase.latest_revision.workspace_id)?.name ?? `#${evalCase.latest_revision.workspace_id}`}</dd></div><div><dt>Validation</dt><dd>{evalCase.latest_revision.validation_status.replace('_', ' ')}</dd></div><div><dt>Revision</dt><dd>v{evalCase.latest_revision.revision}</dd></div></dl>{evalCase.latest_revision.status === 'draft' && <button className="secondary-action" onClick={() => editCase(evalCase)}>Configure</button>}</div>{editingCaseId === evalCase.id && <div className="case-editor"><label>Base commit SHA<input value={baseSha} onChange={(event) => setBaseSha(event.target.value)} placeholder="Full 40-character commit SHA" /></label><label>Verifier command<input value={verifierCommand} onChange={(event) => setVerifierCommand(event.target.value)} placeholder="pytest -q" /></label>{Array.isArray(evalCase.latest_revision.validation_details.problems) && evalCase.latest_revision.validation_details.problems.length > 0 && <ul>{(evalCase.latest_revision.validation_details.problems as string[]).map((problem) => <li key={problem}>{problem}</li>)}</ul>}<div className="case-create-actions"><button className="secondary-action" onClick={() => setEditingCaseId(null)}>Close</button><button className="secondary-action" disabled={loading} onClick={() => void saveDraft(evalCase)}>Save</button><button className="secondary-action" disabled={loading || !evalCase.latest_revision.scorer_spec.length} onClick={() => void caseAction(evalCase, 'validate')}>Validate</button><button className="primary-action" disabled={loading || evalCase.latest_revision.validation_status !== 'valid'} onClick={() => void caseAction(evalCase, 'publish')}>Publish revision</button></div></div>}</article>)}</div>
      </>}

      {section === 'suites' && <><div className="evals-page-header"><div><span className="eyebrow">Versioned collections</span><h1>Suites</h1><p>Freeze ordered collections of published cases.</p></div></div>{error && <div className="evals-error">{error}</div>}<div className="eval-create-row"><input value={newSuiteName} onChange={(event) => setNewSuiteName(event.target.value)} placeholder="Regression suite" /><button className="primary-action" disabled={loading || !newSuiteName.trim()} onClick={() => void createSuite()}><Plus size={14} /> Create suite</button></div><div className="eval-object-list">{suites.map((suite) => <article className="eval-object-card" key={suite.id}><div><span className={`case-status ${suite.latest_version.status === 'frozen' ? 'published' : ''}`}>{suite.latest_version.status}</span><h2>{suite.name}</h2><p>{suite.latest_version.cases.length} published case{suite.latest_version.cases.length === 1 ? '' : 's'} · version {suite.latest_version.version}</p></div>{suite.latest_version.status === 'draft' && <button className="primary-action" disabled={loading || !suite.latest_version.cases.length} onClick={() => void freezeSuite(suite)}>Freeze version</button>}</article>)}</div>{!suites.length && <div className="evals-empty-state compact"><Layers3 size={24} /><h2>No suites yet</h2><p>Publish cases first, then create a frozen collection for repeatable experiments.</p></div>}</>}

      {section === 'configurations' && <><div className="evals-page-header"><div><span className="eyebrow">Controlled inputs</span><h1>Configurations</h1><p>Capture immutable, hashed Codex setups.</p></div></div>{error && <div className="evals-error">{error}</div>}<div className="eval-config-form"><input value={newConfigName} onChange={(event) => setNewConfigName(event.target.value)} placeholder="Configuration name" /><input value={configModel} onChange={(event) => setConfigModel(event.target.value)} placeholder="Model override (optional)" /><select value={reasoningEffort} onChange={(event) => setReasoningEffort(event.target.value)}><option value="low">Low reasoning</option><option value="medium">Medium reasoning</option><option value="high">High reasoning</option><option value="xhigh">Extra-high reasoning</option></select><button className="primary-action" disabled={loading || !newConfigName.trim()} onClick={() => void captureConfig()}><Plus size={14} /> Capture</button></div><div className="eval-object-list">{configs.map((config) => <article className="eval-object-card" key={config.id}><div><span className="case-status published">snapshot</span><h2>{config.name}</h2><p>{config.snapshot.model ?? 'Default model'} · {config.snapshot.reasoning_effort ?? 'default'} reasoning · {config.snapshot.content_hash.slice(0, 10)}</p></div></article>)}</div>{!configs.length && <div className="evals-empty-state compact"><Settings2 size={24} /><h2>No configurations yet</h2><p>Capture the controlled model, reasoning, and sandbox inputs used by an experiment.</p></div>}</>}
    </section>
    {selectedAttempt && <div className="modal-backdrop attempt-backdrop" onClick={() => setSelectedAttempt(null)}><section className="attempt-modal" onClick={(event) => event.stopPropagation()}><div className="attempt-modal-header"><div><span className="eyebrow">Attempt evidence</span><h2>{selectedAttempt.case?.title ?? `Case revision #${selectedAttempt.case_revision_id}`}</h2><p>{selectedAttempt.configuration?.name ?? 'Configuration'} · sample {selectedAttempt.sample_index + 1}</p></div><button className="icon-button" aria-label="Close attempt" onClick={() => setSelectedAttempt(null)}>×</button></div><div className="attempt-overview"><span className={`attempt-outcome ${selectedAttempt.outcome}`}>{selectedAttempt.outcome ?? selectedAttempt.status}</span><dl><div><dt>Agent</dt><dd>{selectedAttempt.durations_ms.agent == null ? '—' : `${selectedAttempt.durations_ms.agent} ms`}</dd></div><div><dt>Setup</dt><dd>{selectedAttempt.durations_ms.setup == null ? '—' : `${selectedAttempt.durations_ms.setup} ms`}</dd></div><div><dt>Scoring</dt><dd>{selectedAttempt.durations_ms.scoring == null ? '—' : `${selectedAttempt.durations_ms.scoring} ms`}</dd></div></dl></div><div className="attempt-evidence"><h3>Scorer evidence</h3>{selectedAttempt.scores.map((score) => <article key={score.key}><div><span className={`score-dot ${score.passed ? 'pass' : 'fail'}`} /><strong>{score.key}</strong><b>{score.passed == null ? 'unavailable' : score.passed ? 'pass' : 'fail'}</b></div><p>{score.summary}</p>{Object.keys(score.evidence).length > 0 && <pre>{JSON.stringify(score.evidence, null, 2)}</pre>}</article>)}{!selectedAttempt.scores.length && <p>No scorer evidence was produced.</p>}<h3>Final diff and artifacts</h3><div className="attempt-artifact-row"><p>{selectedAttempt.diff ? `${selectedAttempt.diff.file_count} changed file${selectedAttempt.diff.file_count === 1 ? '' : 's'}` : 'No final diff is available.'} · {selectedAttempt.artifacts.length} artifact{selectedAttempt.artifacts.length === 1 ? '' : 's'}</p>{selectedAttempt.diff && <button className="secondary-action" onClick={() => setEvalDiff(selectedAttempt.diff)}>Inspect full diff</button>}</div>{selectedAttempt.artifacts.map((artifact) => <div className="artifact-row" key={artifact.id}><span>{artifact.type}</span><code>{artifact.byte_size.toLocaleString()} bytes · {artifact.sha256.slice(0, 12)}</code></div>)}<h3>Normalized steps</h3><div className="attempt-steps">{attemptSteps.map((step) => <article key={step.sequence}><span>{step.sequence}</span><div><strong>{step.title}</strong><p>{step.kind.replaceAll('_', ' ')} · {step.status}{step.duration_ms == null ? '' : ` · ${step.duration_ms} ms`}</p></div></article>)}{!attemptSteps.length && <p>No normalized execution steps are available.</p>}</div><details className="attempt-raw-events"><summary>Raw event previews ({attemptEvents.length})</summary>{attemptEvents.map((event) => <article key={event.id}><strong>#{event.id} · {event.type}</strong><pre>{JSON.stringify(event.payload, null, 2)}</pre></article>)}</details></div></section></div>}
    {evalDiff && <RunDiffView diff={evalDiff} readOnly onClose={() => setEvalDiff(null)} onDecision={async () => undefined} />}
  </div>
}
