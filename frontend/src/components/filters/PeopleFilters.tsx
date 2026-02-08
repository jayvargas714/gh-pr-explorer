import { useFilterStore } from '../../stores/useFilterStore'
import { Select } from '../common/Select'

export function PeopleFilters() {
  const filters = useFilterStore()

  return (
    <div className="mx-filter-section">
      <div className="mx-filter-group">
        <Select
          label="Involves"
          value={filters.involves}
          onChange={(e) => filters.setFilter('involves', e.target.value)}
          options={[
            { value: '', label: 'All Users' },
            // TODO: Populate from repository metadata
          ]}
        />
        <p className="mx-filter-help">
          Author, assignee, mentions, or commenter
        </p>
      </div>

      <div className="mx-filter-group">
        <Select
          label="Mentions"
          value={filters.mentions}
          onChange={(e) => filters.setFilter('mentions', e.target.value)}
          options={[
            { value: '', label: 'All Users' },
            // TODO: Populate from repository metadata
          ]}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Commenter"
          value={filters.commenter}
          onChange={(e) => filters.setFilter('commenter', e.target.value)}
          options={[
            { value: '', label: 'All Users' },
            // TODO: Populate from repository metadata
          ]}
        />
      </div>
    </div>
  )
}
