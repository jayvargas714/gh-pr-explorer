import { useFilterStore } from '../../stores/useFilterStore'
import { Input } from '../common/Input'
import { Select } from '../common/Select'
import { Toggle } from '../common/Toggle'

export function AdvancedFilters() {
  const filters = useFilterStore()

  const searchInOptions = ['title', 'body', 'comments']

  const sortByOptions = [
    { value: '', label: 'Default' },
    { value: 'created', label: 'Created' },
    { value: 'updated', label: 'Updated' },
    { value: 'comments', label: 'Comments' },
    { value: 'reactions', label: 'Reactions' },
    { value: 'interactions', label: 'Interactions' },
  ]

  const sortDirectionOptions = [
    { value: 'desc', label: 'Descending' },
    { value: 'asc', label: 'Ascending' },
  ]

  const limitOptions = [
    { value: '25', label: '25' },
    { value: '30', label: '30' },
    { value: '50', label: '50' },
    { value: '100', label: '100' },
  ]

  const toggleSearchIn = (value: string) => {
    const current = filters.searchIn
    if (current.includes(value)) {
      filters.setFilter(
        'searchIn',
        current.filter((v) => v !== value)
      )
    } else {
      filters.setFilter('searchIn', [...current, value])
    }
  }

  return (
    <div className="mx-filter-section">
      <div className="mx-filter-group">
        <Input
          label="Text Search"
          type="text"
          placeholder="Search keywords..."
          value={filters.search}
          onChange={(e) => filters.setFilter('search', e.target.value)}
        />
      </div>

      <div className="mx-filter-group">
        <label className="mx-filter-label">Search In</label>
        <div className="mx-checkbox-group">
          {searchInOptions.map((option) => (
            <Toggle
              key={option}
              checked={filters.searchIn.includes(option)}
              onChange={() => toggleSearchIn(option)}
              label={option.charAt(0).toUpperCase() + option.slice(1)}
            />
          ))}
        </div>
      </div>

      <div className="mx-filter-group">
        <Input
          label="Comments Count"
          type="text"
          placeholder="e.g., >5, >=10, 0"
          value={filters.comments}
          onChange={(e) => filters.setFilter('comments', e.target.value)}
        />
      </div>

      <div className="mx-filter-group">
        <Input
          label="Reactions Count"
          type="text"
          placeholder="e.g., >=10"
          value={filters.reactions}
          onChange={(e) => filters.setFilter('reactions', e.target.value)}
        />
      </div>

      <div className="mx-filter-group">
        <Input
          label="Interactions Count"
          type="text"
          placeholder="Reactions + Comments"
          value={filters.interactions}
          onChange={(e) => filters.setFilter('interactions', e.target.value)}
        />
      </div>

      <div className="mx-filter-group">
        <Select
          label="Sort By"
          value={filters.sortBy}
          onChange={(e) => filters.setFilter('sortBy', e.target.value)}
          options={sortByOptions}
        />
      </div>

      {filters.sortBy && (
        <div className="mx-filter-group">
          <Select
            label="Sort Direction"
            value={filters.sortDirection}
            onChange={(e) => filters.setFilter('sortDirection', e.target.value)}
            options={sortDirectionOptions}
          />
        </div>
      )}

      <div className="mx-filter-group">
        <Select
          label="Results Limit"
          value={String(filters.limit)}
          onChange={(e) => filters.setFilter('limit', Number(e.target.value))}
          options={limitOptions}
        />
      </div>
    </div>
  )
}
