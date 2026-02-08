import { useFilterStore } from '../../stores/useFilterStore'
import { Select } from '../common/Select'
import { Toggle } from '../common/Toggle'

export function ReviewFilters() {
  const filters = useFilterStore()

  const reviewStatuses = [
    { value: 'none', label: 'No Reviews' },
    { value: 'required', label: 'Review Required' },
    { value: 'approved', label: 'Approved' },
    { value: 'changes_requested', label: 'Changes Requested' },
  ]

  const ciStatuses = [
    { value: 'pending', label: 'Pending' },
    { value: 'success', label: 'Success' },
    { value: 'failure', label: 'Failure' },
  ]

  const toggleReviewStatus = (status: string) => {
    const current = filters.review
    if (current.includes(status)) {
      filters.setFilter(
        'review',
        current.filter((s) => s !== status)
      )
    } else {
      filters.setFilter('review', [...current, status])
    }
  }

  const toggleCIStatus = (status: string) => {
    const current = filters.status
    if (current.includes(status)) {
      filters.setFilter(
        'status',
        current.filter((s) => s !== status)
      )
    } else {
      filters.setFilter('status', [...current, status])
    }
  }

  return (
    <div className="mx-filter-section">
      <div className="mx-filter-group">
        <label className="mx-filter-label">Review Status (OR logic)</label>
        <div className="mx-checkbox-group">
          {reviewStatuses.map((status) => (
            <Toggle
              key={status.value}
              checked={filters.review.includes(status.value)}
              onChange={() => toggleReviewStatus(status.value)}
              label={status.label}
            />
          ))}
        </div>
      </div>

      <div className="mx-filter-group">
        <label className="mx-filter-label">CI Status (OR logic)</label>
        <div className="mx-checkbox-group">
          {ciStatuses.map((status) => (
            <Toggle
              key={status.value}
              checked={filters.status.includes(status.value)}
              onChange={() => toggleCIStatus(status.value)}
              label={status.label}
            />
          ))}
        </div>
      </div>

      <div className="mx-filter-group">
        <Select
          label="Reviewed By"
          value={filters.reviewedBy}
          onChange={(e) => filters.setFilter('reviewedBy', e.target.value)}
          options={[
            { value: '', label: 'All Reviewers' },
            // TODO: Populate from repository metadata
          ]}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Review Requested From"
          value={filters.reviewRequested}
          onChange={(e) => filters.setFilter('reviewRequested', e.target.value)}
          options={[
            { value: '', label: 'All Users' },
            // TODO: Populate from repository metadata
          ]}
        />
      </div>
    </div>
  )
}
