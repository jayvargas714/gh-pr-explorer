import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { SwimlaneColumn } from './SwimlaneColumn'

interface SwimlaneBoardProps {
  onRefresh: () => void
}

export function SwimlaneBoard({ onRefresh }: SwimlaneBoardProps) {
  const lanes = useSwimlaneStore((s) => s.lanes)
  const cardsByLane = useSwimlaneStore((s) => s.cardsByLane)
  const moveCard = useSwimlaneStore((s) => s.moveCard)

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

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over) return

    const activeId = active.id
    const overId = over.id
    if (activeId === overId) return

    const activeIdNum = typeof activeId === 'number' ? activeId : Number(activeId)
    if (!Number.isFinite(activeIdNum)) return

    const fromLaneId = findLaneOfCard(activeIdNum)
    if (fromLaneId == null) return

    let toLaneId: number
    let toIndex: number

    if (typeof overId === 'string' && overId.startsWith('lane-')) {
      toLaneId = Number(overId.slice(5))
      const destList = cardsByLane[toLaneId] ?? []
      // If dropping on same lane's empty space, move to end
      toIndex = fromLaneId === toLaneId
        ? destList.length - 1
        : destList.length
    } else {
      const overIdNum = typeof overId === 'number' ? overId : Number(overId)
      const overLane = findLaneOfCard(overIdNum)
      if (overLane == null) return
      toLaneId = overLane
      const destList = cardsByLane[toLaneId] ?? []
      const overIndex = destList.findIndex((c) => c.id === overIdNum)
      if (overIndex === -1) return

      if (fromLaneId === toLaneId) {
        toIndex = overIndex
      } else {
        // Cross-lane drop: insert at the over card's position
        toIndex = overIndex
      }
    }

    await moveCard(activeIdNum, fromLaneId, toLaneId, toIndex)
  }

  if (lanes.length === 0) {
    return <div className="mx-swl-empty">No swimlanes yet — click "+ Add Lane" to create one.</div>
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCorners} onDragEnd={handleDragEnd}>
      <div className="mx-swl-board">
        {lanes.map((lane) => (
          <SwimlaneColumn
            key={lane.id}
            lane={lane}
            cards={cardsByLane[lane.id] ?? []}
            canDelete={lanes.length > 1}
            onRefresh={onRefresh}
          />
        ))}
      </div>
    </DndContext>
  )
}
