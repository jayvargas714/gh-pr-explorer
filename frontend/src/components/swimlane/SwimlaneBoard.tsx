import { useState } from 'react'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
} from '@dnd-kit/sortable'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { MergeQueueItem } from '../../api/types'
import { SwimlaneColumn } from './SwimlaneColumn'
import { Badge } from '../common/Badge'
import { formatNumber } from '../../utils/formatters'

interface SwimlaneBoardProps {
  onRefresh: () => void
}

export function SwimlaneBoard({ onRefresh }: SwimlaneBoardProps) {
  const lanes = useSwimlaneStore((s) => s.lanes)
  const cardsByLane = useSwimlaneStore((s) => s.cardsByLane)
  const moveCard = useSwimlaneStore((s) => s.moveCard)
  const reorderLanesLocal = useSwimlaneStore((s) => s.reorderLanesLocal)
  const pausePolling = useSwimlaneStore((s) => s.pausePolling)
  const resumePolling = useSwimlaneStore((s) => s.resumePolling)

  // Track the currently-dragged card so DragOverlay can render a floating preview.
  const [activeCard, setActiveCard] = useState<MergeQueueItem | null>(null)

  // Track which lane the cursor is currently over so we can highlight it.
  // Needed because closestCorners often picks a child card as the "over"
  // target instead of the lane droppable, so the lane's own isOver flag is
  // unreliable when the destination lane has any cards.
  const [overLaneId, setOverLaneId] = useState<number | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  const findLaneOfCard = (cardId: number): number | null => {
    for (const laneId of Object.keys(cardsByLane)) {
      const lid = Number(laneId)
      if (cardsByLane[lid]?.some((c) => c.id === cardId)) return lid
    }
    return null
  }

  const handleDragStart = (event: DragStartEvent) => {
    // Hold off background polling while the user is interacting — a refetch
    // mid-drag would re-render the source/destination lists from server state
    // and yank cards out from under the cursor.
    pausePolling()
    const id = event.active.id
    if (typeof id === 'number') {
      for (const list of Object.values(cardsByLane)) {
        const found = list.find((c) => c.id === id)
        if (found) {
          setActiveCard(found)
          return
        }
      }
    }
  }

  const handleDragOver = (event: DragOverEvent) => {
    // Only highlight when dragging a card. Lane reorder drags use string ids
    // prefixed with `swl-`; we don't want them to colour the destination lane.
    if (typeof event.active.id !== 'number') {
      setOverLaneId(null)
      return
    }
    const overId = event.over?.id
    if (overId == null) {
      setOverLaneId(null)
      return
    }
    if (typeof overId === 'string' && overId.startsWith('lane-')) {
      setOverLaneId(Number(overId.slice(5)))
      return
    }
    if (typeof overId === 'number') {
      setOverLaneId(findLaneOfCard(overId))
      return
    }
    setOverLaneId(null)
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    setActiveCard(null)
    setOverLaneId(null)
    // Match the pause taken in handleDragStart. Note: moveCard/reorderLanesLocal
    // also pause around their own network requests, so the depth-counter still
    // suspends polling during the in-flight mutation.
    resumePolling()
    const { active, over } = event
    if (!over) return

    const activeId = active.id
    const overId = over.id
    if (activeId === overId) return

    // Lane reorder: both ids are `swl-N` strings
    if (
      typeof activeId === 'string' &&
      activeId.startsWith('swl-') &&
      typeof overId === 'string' &&
      overId.startsWith('swl-')
    ) {
      const fromLaneId = Number(activeId.slice(4))
      const toLaneId = Number(overId.slice(4))
      const reorderableLanes = lanes.filter((l) => !l.isDefault)
      const fromIndex = reorderableLanes.findIndex((l) => l.id === fromLaneId)
      const toIndex = reorderableLanes.findIndex((l) => l.id === toLaneId)
      if (fromIndex === -1 || toIndex === -1) return
      await reorderLanesLocal(fromIndex, toIndex)
      return
    }

    // Card move: activeId is the card's numeric id
    const activeIdNum = typeof activeId === 'number' ? activeId : Number(activeId)
    if (!Number.isFinite(activeIdNum)) return
    const fromLaneId = findLaneOfCard(activeIdNum)
    if (fromLaneId == null) return

    let toLaneId: number
    let toIndex: number

    if (typeof overId === 'string' && overId.startsWith('lane-')) {
      toLaneId = Number(overId.slice(5))
      const destList = cardsByLane[toLaneId] ?? []
      toIndex = fromLaneId === toLaneId ? Math.max(0, destList.length - 1) : destList.length
    } else if (typeof overId === 'number') {
      const overLane = findLaneOfCard(overId)
      if (overLane == null) return
      toLaneId = overLane
      const destList = cardsByLane[toLaneId] ?? []
      const overIndex = destList.findIndex((c) => c.id === overId)
      if (overIndex === -1) return
      toIndex = overIndex
    } else {
      return
    }

    await moveCard(activeIdNum, fromLaneId, toLaneId, toIndex)
  }

  if (lanes.length === 0) {
    return <div className="mx-swl-empty">No swimlanes yet — click "+ Add Lane" to create one.</div>
  }

  const defaultLane = lanes.find((l) => l.isDefault)
  const otherLanes = lanes.filter((l) => !l.isDefault)
  const sortableIds = otherLanes.map((l) => `swl-${l.id}`)

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={() => {
        setActiveCard(null)
        setOverLaneId(null)
        resumePolling()
      }}
    >
      <div className="mx-swl-board">
        {defaultLane && (
          <SwimlaneColumn
            key={defaultLane.id}
            lane={defaultLane}
            cards={cardsByLane[defaultLane.id] ?? []}
            canDelete={lanes.length > 1}
            sortable={false}
            isHighlighted={overLaneId === defaultLane.id}
            onRefresh={onRefresh}
          />
        )}
        <SortableContext items={sortableIds} strategy={horizontalListSortingStrategy}>
          {otherLanes.map((lane) => (
            <SwimlaneColumn
              key={lane.id}
              lane={lane}
              cards={cardsByLane[lane.id] ?? []}
              canDelete={lanes.length > 1}
              sortable={true}
              isHighlighted={overLaneId === lane.id}
              onRefresh={onRefresh}
            />
          ))}
        </SortableContext>
      </div>

      <DragOverlay dropAnimation={null}>
        {activeCard ? <CardDragPreview card={activeCard} /> : null}
      </DragOverlay>
    </DndContext>
  )
}

/**
 * Lightweight visual stand-in for QueueItem during a drag.
 * Rendering the real QueueItem inside DragOverlay would re-fire its useSortable
 * hook against the same id and conflict with the source card. This preview is
 * presentational only — it shows the same key info (number, title, repo,
 * author, key badges).
 */
function CardDragPreview({ card }: { card: MergeQueueItem }) {
  const stateBadge = () => {
    switch (card.prState) {
      case 'OPEN':
        return <Badge variant="success">Open</Badge>
      case 'CLOSED':
        return <Badge variant="neutral">Closed</Badge>
      case 'MERGED':
        return <Badge variant="info">Merged</Badge>
      default:
        return null
    }
  }
  return (
    <div className="mx-queue-item mx-swl-drag-preview">
      <div className="mx-queue-item__header">
        <div className="mx-queue-item__info">
          <div className="mx-queue-item__title-row">
            <span className="mx-queue-item__title">
              #{card.number} {card.title}
            </span>
            {stateBadge()}
            {card.isDraft && <Badge variant="warning">Draft</Badge>}
          </div>
          <div className="mx-queue-item__meta">
            <span className="mx-queue-item__repo">{card.repo}</span>
            <span className="mx-queue-item__author">by {card.author}</span>
          </div>
        </div>
      </div>
      <div className="mx-queue-item__stats">
        <span className="mx-stats-additions">+{formatNumber(card.additions)}</span>
        <span className="mx-stats-deletions">-{formatNumber(card.deletions)}</span>
      </div>
    </div>
  )
}
