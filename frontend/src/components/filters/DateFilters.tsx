import { useFilterStore } from '../../stores/useFilterStore'
import { Input } from '../common/Input'

export function DateFilters() {
  const filters = useFilterStore()

  return (
    <div className="mx-filter-section">
      <div className="mx-filter-group">
        <label className="mx-filter-label">Created</label>
        <div className="mx-date-range">
          <Input
            type="date"
            placeholder="After"
            value={filters.createdAfter}
            onChange={(e) => filters.setFilter('createdAfter', e.target.value)}
          />
          <span className="mx-date-range__sep">to</span>
          <Input
            type="date"
            placeholder="Before"
            value={filters.createdBefore}
            onChange={(e) => filters.setFilter('createdBefore', e.target.value)}
          />
        </div>
      </div>

      <div className="mx-filter-group">
        <label className="mx-filter-label">Updated</label>
        <div className="mx-date-range">
          <Input
            type="date"
            placeholder="After"
            value={filters.updatedAfter}
            onChange={(e) => filters.setFilter('updatedAfter', e.target.value)}
          />
          <span className="mx-date-range__sep">to</span>
          <Input
            type="date"
            placeholder="Before"
            value={filters.updatedBefore}
            onChange={(e) => filters.setFilter('updatedBefore', e.target.value)}
          />
        </div>
      </div>

      <div className="mx-filter-group">
        <label className="mx-filter-label">Merged</label>
        <div className="mx-date-range">
          <Input
            type="date"
            placeholder="After"
            value={filters.mergedAfter}
            onChange={(e) => filters.setFilter('mergedAfter', e.target.value)}
          />
          <span className="mx-date-range__sep">to</span>
          <Input
            type="date"
            placeholder="Before"
            value={filters.mergedBefore}
            onChange={(e) => filters.setFilter('mergedBefore', e.target.value)}
          />
        </div>
      </div>

      <div className="mx-filter-group">
        <label className="mx-filter-label">Closed</label>
        <div className="mx-date-range">
          <Input
            type="date"
            placeholder="After"
            value={filters.closedAfter}
            onChange={(e) => filters.setFilter('closedAfter', e.target.value)}
          />
          <span className="mx-date-range__sep">to</span>
          <Input
            type="date"
            placeholder="Before"
            value={filters.closedBefore}
            onChange={(e) => filters.setFilter('closedBefore', e.target.value)}
          />
        </div>
      </div>
    </div>
  )
}
