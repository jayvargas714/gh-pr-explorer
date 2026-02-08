import { useWorkflowStore } from '../../stores/useWorkflowStore'
import { Select } from '../common/Select'
import { Button } from '../common/Button'

interface WorkflowFiltersProps {
  workflows: Array<{ id: number; name: string }>
}

export function WorkflowFilters({ workflows }: WorkflowFiltersProps) {
  const { workflowFilters, setWorkflowFilter, resetWorkflowFilters } = useWorkflowStore()

  const eventOptions = [
    { value: '', label: 'All Events' },
    { value: 'push', label: 'Push' },
    { value: 'pull_request', label: 'Pull Request' },
    { value: 'schedule', label: 'Schedule' },
    { value: 'workflow_dispatch', label: 'Manual' },
    { value: 'release', label: 'Release' },
  ]

  const conclusionOptions = [
    { value: '', label: 'All Results' },
    { value: 'success', label: 'Success' },
    { value: 'failure', label: 'Failure' },
    { value: 'cancelled', label: 'Cancelled' },
    { value: 'skipped', label: 'Skipped' },
  ]

  const workflowOptions = [
    { value: '', label: 'All Workflows' },
    ...workflows.map((w) => ({ value: String(w.id), label: w.name })),
  ]

  return (
    <div className="mx-workflow-filters">
      <div className="mx-workflow-filters__row">
        <Select
          label="Workflow"
          value={workflowFilters.workflow}
          onChange={(value) => setWorkflowFilter('workflow', value)}
          options={workflowOptions}
        />

        <Select
          label="Event"
          value={workflowFilters.event}
          onChange={(value) => setWorkflowFilter('event', value)}
          options={eventOptions}
        />

        <Select
          label="Result"
          value={workflowFilters.conclusion}
          onChange={(value) => setWorkflowFilter('conclusion', value)}
          options={conclusionOptions}
        />

        <Button variant="secondary" size="sm" onClick={resetWorkflowFilters}>
          Reset Filters
        </Button>
      </div>
    </div>
  )
}
