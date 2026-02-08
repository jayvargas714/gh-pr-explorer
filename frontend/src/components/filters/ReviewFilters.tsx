import { useFilterStore } from '../../stores/useFilterStore'
import { useMetadataStore } from '../../stores/useMetadataStore'
import { Select } from '../common/Select'
import { Toggle } from '../common/Toggle'

export function ReviewFilters() {
  const filters = useFilterStore()
  const { contributors } = useMetadataStore()

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

  const contributorOptions = [
    { value: '', label: 'All Reviewers' },
    ...contributors.map((c) => ({ value: c, label: c })),
  ]

  const requestedOptions = [
    { value: '', label: 'All Users' },
    ...contributors.map((c) => ({ value: c, label: c })),
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
          options={contributorOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Review Requested From"
          value={filters.reviewRequested}
          onChange={(e) => filters.setFilter('reviewRequested', e.target.value)}
          options={requestedOptions}
        />
      </div>
    </div>
  )
}
