import { useFilterStore } from '../../stores/useFilterStore'
import { useMetadataStore } from '../../stores/useMetadataStore'
import { Select } from '../common/Select'

export function PeopleFilters() {
  const filters = useFilterStore()
  const { contributors } = useMetadataStore()

  const userOptions = [
    { value: '', label: 'All Users' },
    ...contributors.map((c) => ({ value: c, label: c })),
  ]

  return (
    <div className="mx-filter-section">
      <div className="mx-filter-group">
        <Select
          label="Involves"
          value={filters.involves}
          onChange={(e) => filters.setFilter('involves', e.target.value)}
          options={userOptions}
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
          options={userOptions}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Commenter"
          value={filters.commenter}
          onChange={(e) => filters.setFilter('commenter', e.target.value)}
          options={userOptions}
        />
      </div>
    </div>
  )
}
