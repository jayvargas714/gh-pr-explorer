import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { StepContentViewer } from './StepContentViewer'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import type { WorkflowInstance, WorkflowStep } from '../../api/workflow-engine'

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
  completed: 'success',
  running: 'info',
  awaiting_gate: 'warning',
  failed: 'error',
  cancelled: 'neutral',
  pending: 'neutral',
}

const STEP_TYPE_LABELS: Record<string, string> = {
  pr_select: 'PR Select',
  prioritize: 'Prioritize',
  prompt_generate: 'Prompt Generation',
  agent_review: 'Agent Review',
  synthesis: 'Synthesis',
  freshness_check: 'Freshness Check',
  human_gate: 'Human Gate',
  publish: 'Publish',
  expert_select: 'Expert Select',
  holistic_review: 'Holistic Review',
}

const STEP_ICONS: Record<string, string> = {
  pr_select: '🔀',
  prioritize: '📊',
  prompt_generate: '📝',
  agent_review: '🤖',
  synthesis: '🔬',
  freshness_check: '🕐',
  human_gate: '👤',
  publish: '📤',
  expert_select: '🧠',
  holistic_review: '🔭',
}

interface WorkflowRunDetailProps {
  instance: WorkflowInstance
  onBack: () => void
  onOpenGate: () => void
}

function formatDuration(start?: string, end?: string): string {
  if (!start) return '—'
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  const sec = Math.round((e - s) / 1000)
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m ${sec % 60}s`
}

export function WorkflowRunDetail({ instance, onBack, onOpenGate }: WorkflowRunDetailProps) {
  const { selectedInstance, fetchInstance, loading } = useWorkflowEngineStore()
  const [selectedStep, setSelectedStep] = useState<WorkflowStep | null>(null)

  const inst = selectedInstance ?? instance

  useEffect(() => {
    fetchInstance(instance.id)
  }, [instance.id, fetchInstance])

  useEffect(() => {
    if (inst.status === 'running' || inst.status === 'awaiting_gate') {
      const iv = setInterval(() => fetchInstance(inst.id), 5000)
      return () => clearInterval(iv)
    }
  }, [inst.id, inst.status, fetchInstance])

  const steps = inst.steps ?? []
  const artifacts = inst.artifacts ?? []
  const completedCount = steps.filter((s) => s.status === 'completed').length
  const hasGate = steps.some((s) => s.step_type === 'human_gate' && s.status === 'awaiting_gate')

  useEffect(() => {
    if (!selectedStep && steps.length > 0) {
      const active = steps.find((s) => s.status === 'running' || s.status === 'awaiting_gate')
      setSelectedStep(active ?? steps[steps.length - 1])
    }
  }, [steps, selectedStep])

  if (loading && !selectedInstance) {
    return <div className="mx-run-detail__loading"><Spinner /></div>
  }

  return (
    <div className="mx-run-detail">
      <div className="mx-run-detail__header">
        <Button variant="ghost" size="sm" onClick={onBack}>&larr; Back</Button>
        <div className="mx-run-detail__title">
          <h3>Run #{inst.id}</h3>
          <Badge variant={STATUS_VARIANT[inst.status] ?? 'neutral'}>{inst.status}</Badge>
          <span className="mx-run-detail__template">{inst.template_name}</span>
        </div>
        <div className="mx-run-detail__meta">
          <span>{inst.repo}</span>
          <span>{new Date(inst.created_at).toLocaleString()}</span>
        </div>
        {hasGate && (
          <Button variant="primary" size="sm" onClick={onOpenGate}>
            Review Gate
          </Button>
        )}
      </div>

      <div className="mx-run-detail__progress">
        <div className="mx-run-detail__progress-label">
          <span>{completedCount} / {steps.length} steps</span>
          <span>{Math.round((completedCount / Math.max(steps.length, 1)) * 100)}%</span>
        </div>
        <div className="mx-run-detail__progress-bar">
          <div
            className="mx-run-detail__progress-fill"
            style={{ width: `${(completedCount / Math.max(steps.length, 1)) * 100}%` }}
          />
        </div>
      </div>

      <div className="mx-run-detail__panels">
        <div className="mx-run-detail__timeline">
          {steps.map((step) => {
            const isActive = selectedStep?.step_id === step.step_id
            const isRunning = step.status === 'running'
            const isWaiting = step.status === 'awaiting_gate'
            return (
              <button
                key={step.step_id}
                className={`mx-run-detail__step ${isActive ? 'mx-run-detail__step--active' : ''}`}
                onClick={() => setSelectedStep(step)}
              >
                <div className={`mx-run-detail__step-indicator mx-run-detail__step-indicator--${step.status}`}>
                  {isRunning && <span className="mx-run-detail__step-pulse" />}
                  {isWaiting && <span className="mx-run-detail__step-pulse mx-run-detail__step-pulse--warning" />}
                </div>
                <div className="mx-run-detail__step-body">
                  <div className="mx-run-detail__step-top">
                    <span className="mx-run-detail__step-icon">{STEP_ICONS[step.step_type] ?? '⚡'}</span>
                    <span className="mx-run-detail__step-type">
                      {STEP_TYPE_LABELS[step.step_type] ?? step.step_type}
                    </span>
                    <Badge variant={STATUS_VARIANT[step.status] ?? 'neutral'} size="sm">
                      {step.status}
                    </Badge>
                  </div>
                  <div className="mx-run-detail__step-bottom">
                    <span className="mx-run-detail__step-id">{step.step_id}</span>
                    <span className="mx-run-detail__step-duration">
                      {formatDuration(step.started_at, step.completed_at)}
                    </span>
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        <div className="mx-run-detail__content">
          {selectedStep ? (
            <>
              <div className="mx-run-detail__content-header">
                <span className="mx-run-detail__content-icon">{STEP_ICONS[selectedStep.step_type] ?? '⚡'}</span>
                <h4>{STEP_TYPE_LABELS[selectedStep.step_type] ?? selectedStep.step_type}</h4>
                <Badge variant={STATUS_VARIANT[selectedStep.status] ?? 'neutral'} size="sm">
                  {selectedStep.status}
                </Badge>
              </div>
              <div className="mx-run-detail__content-body">
                <StepContentViewer step={selectedStep} artifacts={artifacts} />
              </div>
            </>
          ) : (
            <div className="mx-run-detail__content-empty">Select a step to view its output.</div>
          )}
        </div>
      </div>
    </div>
  )
}
