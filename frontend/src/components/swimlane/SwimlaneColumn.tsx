import { useEffect, useRef, useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { MergeQueueItem, Swimlane, SwimlaneColor } from '../../api/types'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { QueueItem } from '../queue/QueueItem'
import { Button } from '../common/Button'
import { LaneColorPicker } from './LaneColorPicker'

interface SwimlaneColumnProps {
  lane: Swimlane
  cards: MergeQueueItem[]
  canDelete: boolean
  onRefresh: () => void
}

export function SwimlaneColumn({ lane, cards, canDelete, onRefresh }: SwimlaneColumnProps) {
  const renameLane = useSwimlaneStore((s) => s.renameLane)
  const recolorLane = useSwimlaneStore((s) => s.recolorLane)
  const deleteLane = useSwimlaneStore((s) => s.deleteLane)

  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState(lane.name)
  const [showColorPicker, setShowColorPicker] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const colorPickerRef = useRef<HTMLDivElement>(null)

  const { setNodeRef, isOver } = useDroppable({
    id: `lane-${lane.id}`,
    data: { laneId: lane.id, type: 'lane' },
  })

  useEffect(() => {
    setDraftName(lane.name)
  }, [lane.name])

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  // Close color picker on outside click
  useEffect(() => {
    if (!showColorPicker) return
    const onClick = (e: MouseEvent) => {
      if (colorPickerRef.current && !colorPickerRef.current.contains(e.target as Node)) {
        setShowColorPicker(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [showColorPicker])

  const commitRename = () => {
    const trimmed = draftName.trim()
    if (trimmed && trimmed !== lane.name) {
      renameLane(lane.id, trimmed)
    } else {
      setDraftName(lane.name)
    }
    setEditing(false)
  }

  const handleColorChange = (color: SwimlaneColor) => {
    recolorLane(lane.id, color)
    setShowColorPicker(false)
  }

  const handleDelete = () => {
    if (cards.length === 0) {
      deleteLane(lane.id)
      return
    }
    const confirmed = window.confirm(
      `Delete lane "${lane.name}"? Its ${cards.length} card${cards.length === 1 ? '' : 's'} will move to the default lane.`
    )
    if (confirmed) deleteLane(lane.id)
  }

  return (
    <div
      ref={setNodeRef}
      className={`mx-swl-column mx-swl-column--${lane.color}${isOver ? ' mx-swl-column--over' : ''}`}
    >
      <header className="mx-swl-column__header">
        <button
          type="button"
          className={`mx-swl-color-swatch mx-swl-color-swatch--${lane.color} mx-swl-column__color`}
          onClick={() => setShowColorPicker((v) => !v)}
          aria-label="Change lane color"
          data-tooltip="Change color"
        />
        {editing ? (
          <input
            ref={inputRef}
            className="mx-swl-column__name-input"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') {
                setDraftName(lane.name)
                setEditing(false)
              }
            }}
          />
        ) : (
          <h3
            className="mx-swl-column__name"
            onDoubleClick={() => setEditing(true)}
            title="Double-click to rename"
          >
            {lane.name}
            {lane.isDefault && <span className="mx-swl-column__default-tag">default</span>}
          </h3>
        )}
        <span className="mx-swl-column__count">{cards.length}</span>
        {canDelete && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDelete}
            data-tooltip="Delete lane"
          >
            −
          </Button>
        )}
        {showColorPicker && (
          <div ref={colorPickerRef} className="mx-swl-column__color-popover">
            <LaneColorPicker value={lane.color} onChange={handleColorChange} />
          </div>
        )}
      </header>

      <div className="mx-swl-column__body">
        <SortableContext items={cards.map((c) => c.id)} strategy={verticalListSortingStrategy}>
          {cards.length === 0 ? (
            <div className="mx-swl-column__empty">Drop cards here</div>
          ) : (
            cards.map((card, idx) => (
              <QueueItem key={card.id} item={card} index={idx} onRefresh={onRefresh} />
            ))
          )}
        </SortableContext>
      </div>
    </div>
  )
}
