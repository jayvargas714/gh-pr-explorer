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
    workflowsLoading,
    workflowsError,
    workflowsList,
    workflowStats,
    workflowFilters,
    setWorkflowRuns,
    setWorkflowsLoading,
    setWorkflowsError,
    setWorkflowsList,
    setWorkflowStats,
  } = useWorkflowStore()

  useEffect(() => {
    if (selectedRepo) {
      loadWorkflows()
    }
  }, [selectedRepo, workflowFilters])

  const loadWorkflows = async () => {
    if (!selectedRepo) return

    try {
      setWorkflowsLoading(true)
      setWorkflowsError(null)
      const response = await fetchWorkflowRuns(
        selectedRepo.owner.login,
        selectedRepo.name,
        workflowFilters
      )
      setWorkflowRuns(response.runs)
      setWorkflowsList(response.workflows || [])
      setWorkflowStats(response.stats || null)
    } catch (err) {
      setWorkflowsError(err instanceof Error ? err.message : 'Failed to load workflow runs')
    } finally {
      setWorkflowsLoading(false)
    }
  }

  if (workflowsLoading && workflowRuns.length === 0) {
    return (
      <div className="mx-workflows__loading">
        <Spinner size="lg" />
        <p>Loading workflow runs...</p>
      </div>
    )
  }

  if (workflowsError) {
    return <Alert variant="error">{workflowsError}</Alert>
  }

  return (
    <div className="mx-workflows-view">
      <WorkflowFilters workflows={workflowsList} />

      {workflowStats && <WorkflowStats stats={workflowStats} />}

      {workflowRuns.length === 0 ? (
        <Alert variant="info">No workflow runs found matching the current filters.</Alert>
      ) : (
        <WorkflowTable runs={workflowRuns} />
      )}
    </div>
  )
}
