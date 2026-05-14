import { useMemo, useState } from 'react'
import { cardPassesFilters, useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { SwimlaneColor } from '../../api/types'
import { Button } from '../common/Button'
import { CacheTimestamp } from '../common/CacheTimestamp'
import { LaneColorPicker } from './LaneColorPicker'
import { BadgeFilterPopover } from './BadgeFilterPopover'

interface SwimlaneHeaderProps {
  onClose: () => void
  onRefresh: () => void
}

export function SwimlaneHeader({ onClose, onRefresh }: SwimlaneHeaderProps) {
  const createLane = useSwimlaneStore((s) => s.createLane)
  const loading = useSwimlaneStore((s) => s.loading)
  const cardsByLane = useSwimlaneStore((s) => s.cardsByLane)
  const totalCards = useMemo(
    () => Object.values(cardsByLane).reduce((sum, list) => sum + list.length, 0),
    [cardsByLane],
  )
  const lastUpdated = useSwimlaneStore((s) => s.lastUpdated)
  const refreshing = useSwimlaneStore((s) => s.refreshing)
  const searchQuery = useSwimlaneStore((s) => s.searchQuery)
  const setSearchQuery = useSwimlaneStore((s) => s.setSearchQuery)
  const badgeFilters = useSwimlaneStore((s) => s.badgeFilters)
  const badgeFilterMode = useSwimlaneStore((s) => s.badgeFilterMode)
  const clearBadgeFilters = useSwimlaneStore((s) => s.clearBadgeFilters)

  const resetAllFilters = () => {
    setSearchQuery('')
    clearBadgeFilters()
  }

  const filterActive = searchQuery.trim().length > 0 || badgeFilters.size > 0
  const matchCount = useMemo(() => {
    if (!filterActive) return 0
    let n = 0
    for (const list of Object.values(cardsByLane)) {
      for (const card of list) {
        if (cardPassesFilters(card, searchQuery, badgeFilters, badgeFilterMode)) n++
      }
    }
    return n
  }, [cardsByLane, searchQuery, badgeFilters, badgeFilterMode, filterActive])

  const [showAddForm, setShowAddForm] = useState(false)
  const [name, setName] = useState('')
  const [color, setColor] = useState<SwimlaneColor>('info')

  const handleAdd = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    await createLane(trimmed, color)
    setName('')
    setColor('info')
    setShowAddForm(false)
  }

  return (
    <header className="mx-swl-modal__header">
      <div className="mx-swl-modal__title">
        <h2>Swimlane Board</h2>
        <span className="mx-swl-modal__count">{totalCards} cards</span>
        <CacheTimestamp lastUpdated={lastUpdated} refreshing={refreshing} stale={refreshing} />
      </div>

      <div className="mx-swl-modal__search">
        <input
          type="search"
          className="mx-swl-search__input"
          placeholder="Search PR # or text…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setSearchQuery('')
          }}
          aria-label="Search cards"
        />
        {searchQuery && (
          <button
            type="button"
            className="mx-swl-search__clear"
            onClick={() => setSearchQuery('')}
            aria-label="Clear search"
          >
            ×
          </button>
        )}
        <BadgeFilterPopover />
        {filterActive && (
          <button
            type="button"
            className="mx-swl-filter-reset"
            onClick={resetAllFilters}
            data-tooltip="Clear search and badge filters"
            aria-label="Clear all filters"
          >
            Clear all
          </button>
        )}
        {filterActive && (
          <span className="mx-swl-search__count" aria-live="polite">
            {matchCount} match{matchCount === 1 ? '' : 'es'}
          </span>
        )}
      </div>

      <div className="mx-swl-modal__actions">
        {showAddForm ? (
          <div className="mx-swl-add-form">
            <input
              className="mx-swl-add-form__name"
              placeholder="Lane name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAdd()
                if (e.key === 'Escape') setShowAddForm(false)
              }}
              autoFocus
            />
            <LaneColorPicker value={color} onChange={setColor} />
            <Button variant="primary" size="sm" onClick={handleAdd} disabled={!name.trim()}>
              Add
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setShowAddForm(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="primary" size="sm" onClick={() => setShowAddForm(true)}>
            + Add Lane
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={onRefresh} disabled={loading} data-tooltip="Refresh">
          ↻
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
          ✕
        </Button>
      </div>
    </header>
  )
}
