import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Card } from '../common/Card'
import { Spinner } from '../common/Spinner'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { getUsageStats, type TemplateUsageStats } from '../../api/workflow-engine'
import type { WorkflowInstance } from '../../api/workflow-engine'

const STATUS_VARIANTS: Record<string, 'success' | 'error' | 'warning' | 'info' | 'neutral'> = {
  completed: 'success',
  running: 'info',
  pending: 'neutral',
  awaiting_gate: 'warning',
  waiting: 'warning',
  failed: 'error',
  cancelled: 'neutral',
}

type StatusFilter = 'all' | 'running' | 'waiting' | 'completed' | 'failed'

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'waiting', label: 'Awaiting Gate' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
]

function formatStatus(status: string): string {
  return status.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

function matchesFilter(status: string, filter: StatusFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'waiting') return status === 'awaiting_gate' || status === 'waiting'
  if (filter === 'running') return status === 'running' || status === 'pending'
  return status === filter
}

interface WorkflowRunListProps {
  onSelectInstance: (instance: WorkflowInstance) => void
  onNewRun: () => void
  onOpenDomains?: () => void
  onOpenFollowups?: () => void
}

export function WorkflowRunList({ onSelectInstance, onNewRun, onOpenDomains, onOpenFollowups }: WorkflowRunListProps) {
  const { selectedRepo } = useAccountStore()
  const { instances, loadingInstances, error, fetchInstances, cancelRun, clearError } = useWorkflowEngineStore()
  const [filter, setFilter] = useState<StatusFilter>('all')

  const repoFullName = selectedRepo ? `${selectedRepo.owner.login}/${selectedRepo.name}` : ''

  useEffect(() => {
    if (repoFullName) fetchInstances(repoFullName)
  }, [repoFullName, fetchInstances])

  const hasActiveRuns = instances.some(
    (i) => i.status === 'running' || i.status === 'pending' || i.status === 'awaiting_gate'
  )

  useEffect(() => {
    if (!repoFullName || !hasActiveRuns) return
    const iv = setInterval(() => fetchInstances(repoFullName), 5000)
    return () => clearInterval(iv)
  }, [repoFullName, hasActiveRuns, fetchInstances])

  const filtered = instances.filter((i) => matchesFilter(i.status, filter))

  const handleCancel = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    await cancelRun(id)
  }

  return (
    <div className="mx-engine-list">
      <div className="mx-engine-list__header">
        <h3>Workflow Runs</h3>
        <div className="mx-engine-list__actions">
          {onOpenFollowups && (
            <Button variant="ghost" size="sm" onClick={onOpenFollowups}>Follow-Ups</Button>
          )}
          {onOpenDomains && (
            <Button variant="ghost" size="sm" onClick={onOpenDomains}>Expert Domains</Button>
          )}
          <Button variant="primary" size="sm" onClick={onNewRun}>
            + New Run
          </Button>
        </div>
      </div>

      <div className="mx-engine-list__filters">
        {FILTERS.map((f) => {
          const count = f.id === 'all'
            ? instances.length
            : instances.filter((i) => matchesFilter(i.status, f.id)).length
          return (
            <button
              key={f.id}
              className={`mx-engine-list__filter ${filter === f.id ? 'mx-engine-list__filter--active' : ''}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
              <span className="mx-engine-list__filter-count">{count}</span>
            </button>
          )
        })}
      </div>

      <UsageStatsPanel />

      {error && (
        <div className="mx-alert mx-alert--error" style={{ marginBottom: 'var(--mx-space-4)' }}>
          <div className="mx-alert__content">{error}</div>
          <button className="mx-alert__close" onClick={clearError}>x</button>
        </div>
      )}

      {loadingInstances && instances.length === 0 ? (
        <div className="mx-engine-list__loading">
          <Spinner size="lg" />
          <p>Loading workflow runs...</p>
        </div>
      ) : filtered.length === 0 ? (
        <Card className="mx-engine-list__empty">
          <p>{instances.length === 0 ? 'No workflow runs yet. Click "+ New Run" to start one.' : 'No runs match this filter.'}</p>
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
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((inst) => (
                <tr key={inst.id} className="mx-engine-list__row" onClick={() => onSelectInstance(inst)}>
                  <td><span className="mx-engine-list__id">#{inst.id}</span></td>
                  <td>{inst.template_name || `Template #${inst.template_id}`}</td>
                  <td>
                    <Badge variant={STATUS_VARIANTS[inst.status] ?? 'neutral'} size="sm">
                      {formatStatus(inst.status)}
                    </Badge>
                  </td>
                  <td className="mx-engine-list__time">{timeAgo(inst.created_at)}</td>
                  <td className="mx-engine-list__time">{timeAgo(inst.updated_at)}</td>
                  <td>
                    {(inst.status === 'running' || inst.status === 'pending' || inst.status === 'awaiting_gate' || inst.status === 'waiting') && (
                      <Button variant="ghost" size="sm" onClick={(e) => handleCancel(e, inst.id)}>Cancel</Button>
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

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function UsageStatsPanel() {
  const [stats, setStats] = useState<TemplateUsageStats[]>([])
  const [open, setOpen] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!open || loaded) return
    getUsageStats().then((data) => {
      setStats(data)
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [open, loaded])

  if (!open) {
    return (
      <button
        className="mx-engine-list__usage-toggle"
        onClick={() => setOpen(true)}
      >
        Token Usage by Template ▸
      </button>
    )
  }

  return (
    <div className="mx-usage-stats">
      <button
        className="mx-engine-list__usage-toggle mx-engine-list__usage-toggle--open"
        onClick={() => setOpen(false)}
      >
        Token Usage by Template ▾
      </button>
      {stats.length === 0 ? (
        <p className="mx-usage-stats__empty">No usage data yet. Run a workflow to see stats.</p>
      ) : (
        <div className="mx-table-wrapper">
          <table className="mx-table mx-table--compact">
            <thead>
              <tr>
                <th>Template</th>
                <th>Runs</th>
                <th>PRs</th>
                <th title="Average tokens (in+out) per PR">Avg Tokens/PR</th>
                <th title="Average cost per PR">Avg Cost/PR</th>
                <th title="Average tokens per run">Avg Tokens/Run</th>
                <th title="Average cost per run">Avg Cost/Run</th>
              </tr>
            </thead>
            <tbody>
              {stats.map((s) => (
                <tr key={s.template_name}>
                  <td>{s.template_name}</td>
                  <td>{s.run_count}</td>
                  <td>{s.total_prs}</td>
                  <td>{formatTokens(s.avg_input_tokens_per_pr + s.avg_output_tokens_per_pr)}</td>
                  <td>{s.avg_cost_per_pr ? `$${s.avg_cost_per_pr.toFixed(4)}` : '—'}</td>
                  <td>{formatTokens(s.avg_input_tokens_per_run + s.avg_output_tokens_per_run)}</td>
                  <td>{s.avg_cost_per_run ? `$${s.avg_cost_per_run.toFixed(4)}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
