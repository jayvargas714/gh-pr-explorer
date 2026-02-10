import { useState } from 'react'
import { useFilterStore } from '../../stores/useFilterStore'
import { BasicFilters } from './BasicFilters'
import { ReviewFilters } from './ReviewFilters'
import { PeopleFilters } from './PeopleFilters'
import { DateFilters } from './DateFilters'
import { AdvancedFilters } from './AdvancedFilters'
import { Button } from '../common/Button'
import { Badge } from '../common/Badge'

export function FilterPanel() {
  const [isExpanded, setIsExpanded] = useState(true)
  const [activeTab, setActiveTab] = useState<'basic' | 'review' | 'people' | 'dates' | 'advanced'>('basic')

  const resetFilters = useFilterStore((state) => state.resetFilters)
  const activeFiltersCount = useFilterStore((state) => state.getActiveFiltersCount())

  const tabs = [
    { id: 'basic' as const, label: 'Basic', icon: '🔍' },
    { id: 'review' as const, label: 'Review', icon: '👀' },
    { id: 'people' as const, label: 'People', icon: '👥' },
    { id: 'dates' as const, label: 'Dates', icon: '📅' },
    { id: 'advanced' as const, label: 'Advanced', icon: '⚙️' },
  ]

  return (
    <div className={`mx-filter-panel ${isExpanded ? 'mx-filter-panel--expanded' : 'mx-filter-panel--collapsed'}`}>
      <div className="mx-filter-panel__header">
        <button
          className="mx-filter-panel__toggle"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <span className="mx-filter-panel__toggle-icon">{isExpanded ? '▼' : '▶'}</span>
          <span className="mx-filter-panel__title">Filters</span>
          {activeFiltersCount > 0 && (
            <Badge variant="info" size="sm">
              {activeFiltersCount}
            </Badge>
          )}
        </button>

        <Button
          variant="ghost"
          size="sm"
          onClick={resetFilters}
          disabled={activeFiltersCount === 0}
        >
          Reset All
        </Button>
      </div>

      {isExpanded && (
        <>
          <div className="mx-filter-panel__tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`mx-filter-tab ${activeTab === tab.id ? 'mx-filter-tab--active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="mx-filter-tab__icon">{tab.icon}</span>
                <span className="mx-filter-tab__label">{tab.label}</span>
              </button>
            ))}
          </div>

          <div className="mx-filter-panel__content">
            {activeTab === 'basic' && <BasicFilters />}
            {activeTab === 'review' && <ReviewFilters />}
            {activeTab === 'people' && <PeopleFilters />}
            {activeTab === 'dates' && <DateFilters />}
            {activeTab === 'advanced' && <AdvancedFilters />}
          </div>
        </>
      )}
    </div>
  )
}
