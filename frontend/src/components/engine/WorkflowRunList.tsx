import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Card } from '../common/Card'
import { Spinner } from '../common/Spinner'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import { useAccountStore } from '../../stores/useAccountStore'
import type { WorkflowInstance } from '../../api/workflow-engine'

const STATUS_VARIANTS: Record<string, 'success' | 'error' | 'warning' | 'info' | 'neutral'> = {
  completed: 'success',
  running: 'info',
  pending: 'neutral',
  awaiting_gate: 'warning',
  failed: 'error',
  cancelled: 'neutral',
}

function formatStatus(status: string): string {
  return status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function timeAgo(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000)

  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

interface WorkflowRunListProps {
  onSelectInstance: (instance: WorkflowInstance) => void
}

export function WorkflowRunList({ onSelectInstance }: WorkflowRunListProps) {
  const { selectedRepo } = useAccountStore()
  const {
    templates,
    instances,
    loading,
    error,
    fetchTemplates,
    fetchInstances,
    startRun,
    cancelRun,
    clearError,
  } = useWorkflowEngineStore()

  const [selectedTemplate, setSelectedTemplate] = useState<number | null>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    fetchTemplates()
  }, [fetchTemplates])

  const repoFullName = selectedRepo ? `${selectedRepo.owner.login}/${selectedRepo.name}` : ''

  useEffect(() => {
    if (repoFullName) {
      fetchInstances(repoFullName)
    }
  }, [repoFullName, fetchInstances])

  useEffect(() => {
    if (!repoFullName) return
    const interval = setInterval(() => {
      fetchInstances(repoFullName)
    }, 5000)
    return () => clearInterval(interval)
  }, [repoFullName, fetchInstances])

  const handleStartRun = async () => {
    if (!selectedTemplate || !repoFullName) return
    setStarting(true)
    const instanceId = await startRun(selectedTemplate, repoFullName)
    setStarting(false)
    if (instanceId) {
      setSelectedTemplate(null)
    }
  }

  const handleCancel = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    await cancelRun(id)
  }

  return (
    <div className="mx-engine-list">
      <div className="mx-engine-list__header">
        <h3>Workflow Runs</h3>
        <div className="mx-engine-list__actions">
          <select
            className="mx-select"
            value={selectedTemplate ?? ''}
            onChange={(e) => setSelectedTemplate(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Select template...</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <Button
            variant="primary"
            size="sm"
            disabled={!selectedTemplate || !repoFullName || starting}
            onClick={handleStartRun}
          >
            {starting ? <Spinner size="sm" /> : 'Start Run'}
          </Button>
        </div>
      </div>

      {error && (
        <div className="mx-alert mx-alert--error" style={{ marginBottom: 'var(--mx-space-4)' }}>
          <div className="mx-alert__content">{error}</div>
          <button className="mx-alert__close" onClick={clearError}>×</button>
        </div>
      )}

      {loading && instances.length === 0 ? (
        <div className="mx-engine-list__loading">
          <Spinner size="lg" />
          <p>Loading workflow runs...</p>
        </div>
      ) : instances.length === 0 ? (
        <Card className="mx-engine-list__empty">
          <p>No workflow runs yet. Select a template and start one above.</p>
        </Card>
      ) : (
        <div className="mx-table-wrapper">
          <table className="mx-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Template</th>
                <th>Status</th>
                <th>Started</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {instances.map((inst) => (
                <tr
                  key={inst.id}
                  className="mx-engine-list__row"
                  onClick={() => onSelectInstance(inst)}
                >
                  <td>
                    <span className="mx-engine-list__id">#{inst.id}</span>
                  </td>
                  <td>{inst.template_name || `Template #${inst.template_id}`}</td>
                  <td>
                    <Badge variant={STATUS_VARIANTS[inst.status] ?? 'neutral'} size="sm">
                      {formatStatus(inst.status)}
                    </Badge>
                  </td>
                  <td className="mx-engine-list__time">{timeAgo(inst.created_at)}</td>
                  <td className="mx-engine-list__time">{timeAgo(inst.updated_at)}</td>
                  <td>
                    {(inst.status === 'running' || inst.status === 'pending' || inst.status === 'awaiting_gate') && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => handleCancel(e, inst.id)}
                      >
                        Cancel
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
