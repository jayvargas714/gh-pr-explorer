import { useEffect, useCallback } from 'react'
import { useAccountStore } from '../../stores/useAccountStore'
import { useWorkflowStore } from '../../stores/useWorkflowStore'
import { fetchWorkflowRuns } from '../../api/workflows'
import { WorkflowFilters } from './WorkflowFilters'
import { WorkflowStats } from './WorkflowStats'
import { WorkflowTable } from './WorkflowTable'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

export function WorkflowsView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const workflowRuns = useWorkflowStore((s) => s.workflowRuns)
  const loading = useWorkflowStore((s) => s.loading)
  const refreshing = useWorkflowStore((s) => s.refreshing)
  const error = useWorkflowStore((s) => s.error)
  const workflows = useWorkflowStore((s) => s.workflows)
  const workflowStats = useWorkflowStore((s) => s.workflowStats)
  const workflowFilter = useWorkflowStore((s) => s.workflowFilter)
  const branchFilter = useWorkflowStore((s) => s.branchFilter)
  const eventFilter = useWorkflowStore((s) => s.eventFilter)
  const conclusionFilter = useWorkflowStore((s) => s.conclusionFilter)

  const loadWorkflows = useCallback(async (refresh = false) => {
    if (!selectedRepo) return

    const {
      setLoading,
      setRefreshing,
      setError,
      setWorkflowRuns,
      setWorkflows,
      setWorkflowStats,
    } = useWorkflowStore.getState()

    try {
      if (refresh) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      setError(null)
      const filters: Record<string, string> = {}
      if (workflowFilter) filters.workflow_id = workflowFilter
      if (branchFilter) filters.branch = branchFilter
      if (eventFilter) filters.event = eventFilter
      if (conclusionFilter) filters.conclusion = conclusionFilter
      if (refresh) filters.refresh = 'true'

      const response = await fetchWorkflowRuns(
        selectedRepo.owner.login,
        selectedRepo.name,
        filters
      )

      setWorkflowRuns(response.runs)
      setWorkflows(response.workflows || [])
      setWorkflowStats(response.stats || null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflow runs')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [selectedRepo, workflowFilter, branchFilter, eventFilter, conclusionFilter])

  useEffect(() => {
    if (!selectedRepo) return
    loadWorkflows()
  }, [selectedRepo, workflowFilter, branchFilter, eventFilter, conclusionFilter, loadWorkflows])

  const handleRefreshCache = useCallback(() => {
    loadWorkflows(true)
  }, [loadWorkflows])

  if (loading && workflowRuns.length === 0) {
    return (
      <div className="mx-workflows__loading">
        <Spinner size="lg" />
        <p>Loading workflow runs...</p>
      </div>
    )
  }

  if (error) {
    return <Alert variant="error">{error}</Alert>
  }

  const isRefetching = (loading || refreshing) && workflowRuns.length > 0

  return (
    <div className="mx-workflows-view">
      <WorkflowFilters
        workflows={workflows}
        onRefreshCache={handleRefreshCache}
        refreshing={refreshing}
      />

      <div className="mx-workflows__content">
        {isRefetching && (
          <div className="mx-workflows__overlay">
            <Spinner size="lg" />
          </div>
        )}

        {workflowStats && <WorkflowStats stats={workflowStats} />}

        {!loading && workflowRuns.length === 0 ? (
          <Alert variant="info">No workflow runs found matching the current filters.</Alert>
        ) : (
          workflowRuns.length > 0 && <WorkflowTable runs={workflowRuns} />
        )}
      </div>
    </div>
  )
}
