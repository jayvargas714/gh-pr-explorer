import { useEffect, useRef, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { StepContentViewer } from './StepContentViewer'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import { retryStep, getStepDownloadUrl, getInstanceFeedback, clearInstanceFeedback } from '../../api/workflow-engine'
import type { WorkflowInstance } from '../../api/workflow-engine'

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
  const { selectedInstance, fetchInstance, loadingInstance } = useWorkflowEngineStore()
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)

  const inst = selectedInstance ?? instance

  useEffect(() => {
    fetchInstance(instance.id)
  }, [instance.id, fetchInstance])

  useEffect(() => {
    if (inst.status === 'running' || inst.status === 'awaiting_gate') {
      const iv = setInterval(() => fetchInstance(inst.id), 3000)
      return () => clearInterval(iv)
    }
  }, [inst.id, inst.status, fetchInstance])

  const steps = inst.steps ?? []
  const artifacts = inst.artifacts ?? []
  const completedCount = steps.filter((s) => s.status === 'completed').length
  const hasGate = steps.some((s) => s.step_type === 'human_gate' && s.status === 'awaiting_gate')
  const selectedStep = steps.find((s) => s.step_id === selectedStepId) ?? null

  const prevSelectedRef = useRef<{ stepId: string | null; status: string | null }>({ stepId: null, status: null })

  useEffect(() => {
    if (!selectedStepId && steps.length > 0) {
      const active = steps.find((s) => s.status === 'running' || s.status === 'awaiting_gate')
      setSelectedStepId((active ?? steps[steps.length - 1]).step_id)
      return
    }
    const sel = steps.find((s) => s.step_id === selectedStepId)
    if (!sel) return
    const prev = prevSelectedRef.current
    const sameStep = prev.stepId === selectedStepId
    const wasRunning = sameStep && prev.status === 'running'
    prevSelectedRef.current = { stepId: selectedStepId, status: sel.status }
    if (wasRunning && (sel.status === 'completed' || sel.status === 'failed')) {
      const next = steps.find((s) => s.status === 'running' || s.status === 'awaiting_gate')
      if (next) setSelectedStepId(next.step_id)
    }
  }, [steps, selectedStepId])

  if (loadingInstance && !selectedInstance) {
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
                onClick={() => setSelectedStepId(step.step_id)}
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
                {selectedStep.status === 'completed' && (
                  <>
                    <a
                      href={getStepDownloadUrl(inst.id, selectedStep.step_id, 'md')}
                      download
                      style={{ textDecoration: 'none' }}
                    >
                      <Button variant="ghost" size="sm">↓ .md</Button>
                    </a>
                    <a
                      href={getStepDownloadUrl(inst.id, selectedStep.step_id, 'json')}
                      download
                      style={{ textDecoration: 'none' }}
                    >
                      <Button variant="ghost" size="sm">↓ .json</Button>
                    </a>
                  </>
                )}
                {(selectedStep.status === 'completed' || selectedStep.status === 'failed') && (
                  <RetryButton instanceId={inst.id} stepId={selectedStep.step_id} onRetried={() => fetchInstance(inst.id)} />
                )}
              </div>
              <div className="mx-run-detail__content-body">
                <StepContentViewer step={selectedStep} artifacts={artifacts} instanceId={inst.id} />
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


function RetryButton({ instanceId, stepId, onRetried }: { instanceId: number; stepId: string; onRetried: () => void }) {
  const [hasFeedback, setHasFeedback] = useState(false)
  const [feedbackText, setFeedbackText] = useState('')
  const checked = useRef(false)

  useEffect(() => {
    if (checked.current) return
    checked.current = true
    getInstanceFeedback(instanceId).then(({ human_feedback }) => {
      const relevant = human_feedback.filter((fb) => fb.retry_target === stepId)
      if (relevant.length > 0) {
        setHasFeedback(true)
        setFeedbackText(relevant.map((fb) => fb.feedback).join('; '))
      }
    }).catch(() => {})
  }, [instanceId, stepId])

  const handleRetry = async (clearFb: boolean) => {
    const msg = clearFb
      ? `Retry from "${stepId}" and clear stale feedback? This will re-run this step and all downstream steps.`
      : `Retry from "${stepId}"? This will re-run this step and all downstream steps.`
    if (!confirm(msg)) return
    await retryStep(instanceId, stepId, clearFb)
    onRetried()
  }

  const handleClearOnly = async () => {
    await clearInstanceFeedback(instanceId)
    setHasFeedback(false)
    setFeedbackText('')
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      {hasFeedback && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }} title={`Stale feedback: "${feedbackText}"`}>
          <Badge variant="warning" size="sm">has feedback</Badge>
          <Button variant="ghost" size="sm" onClick={() => handleRetry(true)}>
            ↻ Retry (clear feedback)
          </Button>
          <Button variant="ghost" size="sm" onClick={handleClearOnly} title="Clear stale feedback without retrying">
            ✕
          </Button>
        </div>
      )}
      <Button variant="ghost" size="sm" onClick={() => handleRetry(false)}>
        ↻ Retry from here
      </Button>
    </div>
  )
}
