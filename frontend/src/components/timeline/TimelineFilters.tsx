import type { TimelineEventType } from '../../api/types'
import { useTimelineStore, timelineKey } from '../../stores/useTimelineStore'

interface Props {
  owner: string
  repo: string
  prNumber: number
}

const FILTER_GROUPS: Array<{ label: string; types: TimelineEventType[]; color: string }> = [
  { label: 'Commits', types: ['committed', 'head_ref_force_pushed'], color: '#10b981' },
  { label: 'Reviews', types: ['reviewed', 'review_requested'], color: '#f59e0b' },
  { label: 'Comments', types: ['commented'], color: '#06b6d4' },
  { label: 'State', types: ['opened', 'closed', 'reopened', 'merged', 'ready_for_review', 'convert_to_draft'], color: '#8b5cf6' },
]

export function TimelineFilters({ owner, repo, prNumber }: Props) {
  const key = timelineKey(owner, repo, prNumber)
  const entry = useTimelineStore((s) => s.timelines[key])
  const toggleType = useTimelineStore((s) => s.toggleType)

  if (!entry) return null

  return (
    <div className="tl-filters" role="group" aria-label="Filter timeline events">
      {FILTER_GROUPS.map((group) => {
        const allHidden = group.types.every((t) => entry.hiddenTypes.has(t))
        const isActive = !allHidden
        return (
          <button
            key={group.label}
            type="button"
            role="switch"
            aria-checked={isActive}
            className={`tl-chip${isActive ? ' tl-chip--active' : ''}`}
            onClick={() => group.types.forEach((t) => toggleType(key, t))}
          >
            <span className="tl-chip__dot" style={{ background: group.color }} />
            {group.label}
          </button>
        )
      })}
    </div>
  )
}
