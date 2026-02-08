import { useFilterStore } from '../../stores/useFilterStore'
import { useMetadataStore } from '../../stores/useMetadataStore'
import { Select } from '../common/Select'
import { Toggle } from '../common/Toggle'

export function BasicFilters() {
  const filters = useFilterStore()
  const { contributors, branches, milestones } = useMetadataStore()

  const stateOptions = [
    { value: 'open', label: 'Open' },
    { value: 'closed', label: 'Closed' },
    { value: 'merged', label: 'Merged' },
    { value: 'all', label: 'All' },
  ]

  const draftOptions = [
    { value: '', label: 'Any' },
    { value: 'false', label: 'Ready for Review' },
    { value: 'true', label: 'Draft' },
  ]

  const linkedOptions = [
    { value: '', label: 'Any' },
    { value: 'true', label: 'Linked to Issue' },
    { value: 'false', label: 'Not Linked' },
  ]

  const contributorOptions = [
    { value: '', label: 'All Authors' },
    ...contributors.map((c) => ({ value: c, label: c })),
  ]

  const assigneeOptions = [
    { value: '', label: 'All Assignees' },
    ...contributors.map((c) => ({ value: c, label: c })),
  ]

  const branchOptions = [
    { value: '', label: 'All Branches' },
    ...branches.map((b) => ({ value: b, label: b })),
  ]

  const milestoneOptions = [
    { value: '', label: 'All Milestones' },
    { value: 'none', label: 'No Milestone' },
    ...milestones.map((m) => ({ value: m.title, label: m.title })),
  ]

  return (
    <div className="mx-filter-section">
      <div className="mx-filter-group">
        <label className="mx-filter-label">State</label>
        <div className="mx-button-group">
          {stateOptions.map((option) => (
            <button
              key={option.value}
              className={`mx-button-group__item ${
                filters.state === option.value ? 'mx-button-group__item--active' : ''
              }`}
              onClick={() => filters.setFilter('state', option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mx-filter-group">
        <Select
          label="Draft Status"
          value={filters.draft}
          onChange={(e) => filters.setFilter('draft', e.target.value)}
          options={draftOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Author"
          value={filters.author}
          onChange={(e) => filters.setFilter('author', e.target.value)}
          options={contributorOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Assignee"
          value={filters.assignee}
          onChange={(e) => filters.setFilter('assignee', e.target.value)}
          options={assigneeOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Toggle
          checked={filters.noAssignee}
          onChange={(checked) => filters.setFilter('noAssignee', checked)}
          label="No Assignee"
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Base Branch"
          value={filters.base}
          onChange={(e) => filters.setFilter('base', e.target.value)}
          options={branchOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Head Branch"
          value={filters.head}
          onChange={(e) => filters.setFilter('head', e.target.value)}
          options={branchOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Toggle
          checked={filters.noLabel}
          onChange={(checked) => filters.setFilter('noLabel', checked)}
          label="No Labels"
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Milestone"
          value={filters.milestone}
          onChange={(e) => filters.setFilter('milestone', e.target.value)}
          options={milestoneOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Linked to Issue"
          value={filters.linked}
          onChange={(e) => filters.setFilter('linked', e.target.value)}
          options={linkedOptions}
        />
      </div>
    </div>
  )
}
