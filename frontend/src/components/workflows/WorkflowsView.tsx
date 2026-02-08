import { useEffect } from 'react'
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
  const {
    workflowRuns,
    loading,
    error,
    workflows,
    workflowStats,
    workflowFilter,
    branchFilter,
    eventFilter,
    conclusionFilter,
    setWorkflowRuns,
    setLoading,
    setError,
    setWorkflows,
    setWorkflowStats,
  } = useWorkflowStore()

  useEffect(() => {
    if (selectedRepo) {
      loadWorkflows()
    }
  }, [selectedRepo, workflowFilter, branchFilter, eventFilter, conclusionFilter])

  const loadWorkflows = async () => {
    if (!selectedRepo) return

    try {
      setLoading(true)
      setError(null)
      const filters: Record<string, string> = {}
      if (workflowFilter) filters.workflow_id = workflowFilter
      if (branchFilter) filters.branch = branchFilter
      if (eventFilter) filters.event = eventFilter
      if (conclusionFilter) filters.conclusion = conclusionFilter

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
    }
  }

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

  return (
    <div className="mx-workflows-view">
      <WorkflowFilters workflows={workflows} />

      {workflowStats && <WorkflowStats stats={workflowStats} />}

      {workflowRuns.length === 0 ? (
        <Alert variant="info">No workflow runs found matching the current filters.</Alert>
      ) : (
        <WorkflowTable runs={workflowRuns} />
      )}
    </div>
  )
}
