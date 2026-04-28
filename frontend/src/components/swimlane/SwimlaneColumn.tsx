import { useEffect, useRef, useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { MergeQueueItem, Swimlane, SwimlaneColor } from '../../api/types'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { QueueItem } from '../queue/QueueItem'
import { Button } from '../common/Button'
import { LaneColorPicker } from './LaneColorPicker'

interface SwimlaneColumnProps {
  lane: Swimlane
  cards: MergeQueueItem[]
  canDelete: boolean
  /** When true, the column header exposes a drag handle for left/right reordering. */
  sortable: boolean
  /** Resolved at the board level: true when the cursor is over this lane (or a card it owns). */
  isHighlighted: boolean
  onRefresh: () => void
}

export function SwimlaneColumn({ lane, cards, canDelete, sortable, isHighlighted, onRefresh }: SwimlaneColumnProps) {
  const renameLane = useSwimlaneStore((s) => s.renameLane)
  const recolorLane = useSwimlaneStore((s) => s.recolorLane)
  const deleteLane = useSwimlaneStore((s) => s.deleteLane)

  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState(lane.name)
  const [showColorPicker, setShowColorPicker] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const colorPickerRef = useRef<HTMLDivElement>(null)

  // Card destination droppable — id has `lane-` prefix so it never collides with card numeric ids.
  // Note: we don't use isOver here for highlighting; the board computes overLaneId for us
  // so the lane stays highlighted even when the cursor is over a child card.
  const { setNodeRef: setBodyRef } = useDroppable({
    id: `lane-${lane.id}`,
    data: { laneId: lane.id, type: 'lane' },
  })

  // Column reordering — the column itself is a sortable item among other columns.
  const {
    attributes: sortAttrs,
    listeners: sortListeners,
    setNodeRef: setColumnRef,
    transform: columnTransform,
    transition: columnTransition,
    isDragging: isColumnDragging,
  } = useSortable({
    id: `swl-${lane.id}`,
    data: { type: 'lane-handle', laneId: lane.id },
    disabled: !sortable,
  })

  const columnStyle = {
    transform: CSS.Transform.toString(columnTransform),
    transition: columnTransition,
  }

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

  const className = [
    'mx-swl-column',
    `mx-swl-column--${lane.color}`,
    isHighlighted ? 'mx-swl-column--over' : '',
    isColumnDragging ? 'mx-swl-column--reordering' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div ref={setColumnRef} style={columnStyle} className={className}>
      <header className="mx-swl-column__header">
        {sortable && (
          <button
            type="button"
            className="mx-swl-column__drag-handle"
            {...sortAttrs}
            {...sortListeners}
            aria-label="Drag to reorder lane"
            data-tooltip="Drag to reorder lane"
          >
            ⋮⋮
          </button>
        )}
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

      <div ref={setBodyRef} className="mx-swl-column__body">
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
