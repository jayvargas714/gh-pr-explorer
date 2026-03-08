import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Card } from '../common/Card'
import { Spinner } from '../common/Spinner'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import { getTemplate, getAvailableStepTypes } from '../../api/workflow-engine'
import type { WorkflowTemplate } from '../../api/workflow-engine'

const STEP_TYPE_LABELS: Record<string, string> = {
  pr_select: 'PR Select',
  prioritize: 'Prioritize',
  prompt_generate: 'Prompt Gen',
  agent_review: 'Agent Review',
  synthesis: 'Synthesis',
  freshness_check: 'Freshness',
  human_gate: 'Human Gate',
  publish: 'Publish',
  expert_select: 'Expert Select',
  holistic_review: 'Holistic Review',
  followup_check: 'Follow-Up Check',
  followup_action: 'Follow-Up Action',
}

const MODE_NOTES: Record<string, string> = {
  'self-review': 'Local only — will not publish to GitHub',
  'deep-review': 'Will publish to GitHub after human approval',
  'team-review': 'Batch review — publishes all approved PRs',
  'quick': 'Single-agent quick review',
}

function getTemplateMode(steps: TemplateStepDef[]): string {
  const prSelect = steps.find(s => s.type === 'pr_select')
  return (prSelect?.config?.mode as string) ?? 'team-review'
}

interface TemplateStepDef {
  id: string
  type: string
  config?: Record<string, unknown>
}

interface RunConfigPanelProps {
  repo: string
  onClose: () => void
  onStarted: (instanceId: number) => void
}

export function RunConfigPanel({ repo, onClose, onStarted }: RunConfigPanelProps) {
  const { templates, agents, fetchTemplates, fetchAgents, startRun, loading } = useWorkflowEngineStore()
  const [selected, setSelected] = useState<WorkflowTemplate | null>(null)
  const [templateDetail, setTemplateDetail] = useState<Record<string, unknown> | null>(null)
  const [agentOverrides, setAgentOverrides] = useState<Record<string, string>>({})
  const [starting, setStarting] = useState(false)
  const [availableTypes, setAvailableTypes] = useState<string[]>([])
  const [templateStepTypes, setTemplateStepTypes] = useState<Record<number, string[]>>({})

  const [prMode, setPrMode] = useState<'all' | 'specific'>('all')
  const [specificPrs, setSpecificPrs] = useState('')
  const [batchSize, setBatchSize] = useState(10)

  useEffect(() => {
    fetchTemplates()
    fetchAgents()
    getAvailableStepTypes()
      .then((r) => setAvailableTypes(r.available))
      .catch(() => setAvailableTypes([]))
  }, [fetchTemplates, fetchAgents])

  useEffect(() => {
    for (const t of templates) {
      if (templateStepTypes[t.id]) continue
      getTemplate(t.id).then((detail) => {
        const tmpl = detail.template ?? (detail.template_json ? JSON.parse(detail.template_json as string) : null)
        const types = (tmpl?.steps as TemplateStepDef[] ?? []).map((s: TemplateStepDef) => s.type)
        setTemplateStepTypes((prev) => ({ ...prev, [t.id]: types }))
      }).catch(() => {/* ignore */})
    }
  }, [templates, templateStepTypes])

  useEffect(() => {
    if (!selected) {
      setTemplateDetail(null)
      setAgentOverrides({})
      return
    }
    getTemplate(selected.id).then((t) => {
      const tmpl = t.template ?? (t.template_json ? JSON.parse(t.template_json as string) : null)
      setTemplateDetail(tmpl as Record<string, unknown>)
    }).catch(() => setTemplateDetail(null))
  }, [selected])

  const steps: TemplateStepDef[] = templateDetail
    ? (templateDetail.steps as TemplateStepDef[]) ?? []
    : []

  const agentSteps = steps.filter((s) => s.type === 'agent_review')

  const getMissingTypes = (templateId: number): string[] => {
    const types = templateStepTypes[templateId] ?? []
    if (availableTypes.length === 0) return []
    return types.filter((t) => !availableTypes.includes(t))
  }

  const selectedMissing = selected ? getMissingTypes(selected.id) : []
  const canStart = selected && selectedMissing.length === 0

  const handleStart = async () => {
    if (!selected || !canStart) return
    setStarting(true)
    const config: Record<string, unknown> = {}
    if (Object.keys(agentOverrides).length > 0) {
      config.agent_overrides = agentOverrides
    }
    const stepOverrides: Record<string, Record<string, unknown>> = {}
    if (prMode === 'specific' && specificPrs.trim()) {
      const nums = specificPrs.split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n))
      if (nums.length > 0) {
        const selectStep = steps.find((s) => s.type === 'pr_select')
        if (selectStep) {
          stepOverrides[selectStep.id] = { pr_numbers: nums }
        }
      }
    }
    const prioritizeStep = steps.find((s) => s.type === 'prioritize')
    if (prioritizeStep && batchSize !== 10) {
      stepOverrides[prioritizeStep.id] = { max_batch: batchSize }
    }
    if (Object.keys(stepOverrides).length > 0) {
      config.step_overrides = stepOverrides
    }
    const id = await startRun(selected.id, repo, config)
    setStarting(false)
    if (id) onStarted(id)
  }

  return (
    <div className="mx-run-config">
      <div className="mx-run-config__header">
        <h3>New Review Run</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
      </div>

      <div className="mx-run-config__repo">
        <span className="mx-run-config__repo-label">Repository</span>
        <code>{repo}</code>
      </div>

      <div className="mx-run-config__section">
        <h4>Choose Template</h4>
        <div className="mx-run-config__templates">
          {templates.map((t) => {
            const missing = getMissingTypes(t.id)
            const isDisabled = missing.length > 0
            const tplSteps = (templateStepTypes[t.id] ?? [])
            const tplMode = getTemplateMode(
              tplSteps.map(type => ({ id: '', type, config: {} }))
            )
            return (
              <Card
                key={t.id}
                hover={!isDisabled}
                className={[
                  'mx-run-config__tpl-card',
                  selected?.id === t.id ? 'mx-run-config__tpl-card--selected' : '',
                  isDisabled ? 'mx-run-config__tpl-card--disabled' : '',
                ].filter(Boolean).join(' ')}
                onClick={() => { if (!isDisabled) setSelected(t) }}
              >
                <div className="mx-run-config__tpl-name">
                  {t.name}
                  {t.is_builtin && <Badge variant="neutral" size="sm">Built-in</Badge>}
                  {isDisabled && <Badge variant="warning" size="sm">Not Available</Badge>}
                </div>
                <p className="mx-run-config__tpl-desc">{t.description}</p>
                {MODE_NOTES[tplMode] && (
                  <span className="mx-run-config__mode-note">{MODE_NOTES[tplMode]}</span>
                )}
                {isDisabled && (
                  <p className="mx-run-config__tpl-missing">
                    Requires: {missing.map((m) => STEP_TYPE_LABELS[m] ?? m).join(', ')}
                  </p>
                )}
              </Card>
            )
          })}
        </div>
      </div>

      {selected && !selectedMissing.length && (
        <div className="mx-run-config__section">
          <h4>PR Selection</h4>
          <div className="mx-run-config__pr-mode">
            <label className="mx-run-config__radio">
              <input
                type="radio"
                name="prMode"
                checked={prMode === 'all'}
                onChange={() => setPrMode('all')}
              />
              All open PRs
            </label>
            <label className="mx-run-config__radio">
              <input
                type="radio"
                name="prMode"
                checked={prMode === 'specific'}
                onChange={() => setPrMode('specific')}
              />
              Specific PRs
            </label>
          </div>
          {prMode === 'specific' && (
            <input
              className="mx-input"
              type="text"
              placeholder="PR numbers (comma-separated, e.g. 42, 57, 103)"
              value={specificPrs}
              onChange={(e) => setSpecificPrs(e.target.value)}
            />
          )}
          {steps.some((s) => s.type === 'prioritize') && (
            <div className="mx-run-config__batch">
              <label>Max PRs per batch</label>
              <input
                className="mx-input mx-run-config__batch-input"
                type="number"
                min={1}
                max={50}
                value={batchSize}
                onChange={(e) => setBatchSize(parseInt(e.target.value, 10) || 10)}
              />
            </div>
          )}
        </div>
      )}

      {selected && steps.length > 0 && !selectedMissing.length && (
        <div className="mx-run-config__section">
          <h4>Pipeline Preview</h4>
          <div className="mx-run-config__steps">
            {steps.map((s, i) => (
              <div key={s.id} className="mx-run-config__step">
                <span className="mx-run-config__step-num">{i + 1}</span>
                <span className="mx-run-config__step-type">
                  {STEP_TYPE_LABELS[s.type] ?? s.type}
                </span>
                <span className="mx-run-config__step-id">{s.id}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {selected && agentSteps.length > 0 && agents.length > 0 && !selectedMissing.length && (
        <div className="mx-run-config__section">
          <h4>Agent Assignment</h4>
          <div className="mx-run-config__agents">
            {agentSteps.map((s) => {
              const defaultAgent = (s.config?.agent as string) ?? ''
              return (
                <div key={s.id} className="mx-run-config__agent-row">
                  <label>{s.id}</label>
                  <select
                    className="mx-select"
                    value={agentOverrides[s.id] ?? defaultAgent}
                    onChange={(e) =>
                      setAgentOverrides((prev) => ({ ...prev, [s.id]: e.target.value }))
                    }
                  >
                    {agents.filter((a) => a.is_active).map((a) => (
                      <option key={a.name} value={a.name}>
                        {a.name} ({a.model})
                      </option>
                    ))}
                  </select>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="mx-run-config__footer">
        <Button
          variant="primary"
          disabled={!canStart || starting || loading}
          onClick={handleStart}
        >
          {starting ? <Spinner size="sm" /> : 'Start Run'}
        </Button>
      </div>
    </div>
  )
}
