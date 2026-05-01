import { useState } from 'react'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { SwimlaneColor } from '../../api/types'
import { Button } from '../common/Button'
import { CacheTimestamp } from '../common/CacheTimestamp'
import { LaneColorPicker } from './LaneColorPicker'

interface SwimlaneHeaderProps {
  onClose: () => void
  onRefresh: () => void
}

export function SwimlaneHeader({ onClose, onRefresh }: SwimlaneHeaderProps) {
  const createLane = useSwimlaneStore((s) => s.createLane)
  const loading = useSwimlaneStore((s) => s.loading)
  const totalCards = useSwimlaneStore((s) =>
    Object.values(s.cardsByLane).reduce((sum, list) => sum + list.length, 0)
  )
  const lastUpdated = useSwimlaneStore((s) => s.lastUpdated)
  const refreshing = useSwimlaneStore((s) => s.refreshing)

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
