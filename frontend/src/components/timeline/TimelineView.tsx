import { motion } from 'framer-motion'
import type { TimelineEvent } from '../../api/types'
import { useTimelineStore, timelineKey } from '../../stores/useTimelineStore'
import { TimelineEventRow } from './TimelineEventRow'

interface Props {
  owner: string
  repo: string
  prNumber: number
}

export function TimelineView({ owner, repo, prNumber }: Props) {
  const key = timelineKey(owner, repo, prNumber)
  const entry = useTimelineStore((s) => s.timelines[key])
  const toggleExpanded = useTimelineStore((s) => s.toggleExpanded)
  const resetFilters = useTimelineStore((s) => s.resetFilters)

  if (!entry) return null

  if (entry.loading) {
    return (
      <div>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="tl-skeleton" />
        ))}
      </div>
    )
  }

  if (entry.error) {
    return (
      <div className="tl-error">
        Failed to load timeline: {entry.error}
      </div>
    )
  }

  const visibleEvents: TimelineEvent[] = entry.events.filter(
    (e) => !entry.hiddenTypes.has(e.type)
  )

  if (visibleEvents.length === 0) {
    return (
      <div className="tl-empty">
        {entry.events.length === 0
          ? 'No events yet.'
          : (
            <>
              No events match the selected filters.{' '}
              <button type="button" onClick={() => resetFilters(key)}
                      style={{ background: 'none', border: 'none', color: 'var(--mx-accent, #6366f1)',
                               cursor: 'pointer', textDecoration: 'underline' }}>
                Reset filters
              </button>
            </>
          )}
      </div>
    )
  }

  return (
    <div className="tl-rail">
      {visibleEvents.map((event, i) => (
        <motion.div
          key={event.id}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            type: 'spring',
            damping: 28,
            stiffness: 320,
            delay: i < 20 ? i * 0.04 : 0,
          }}
        >
          <TimelineEventRow
            event={event}
            expanded={entry.expandedIds.has(event.id)}
            onToggle={() => toggleExpanded(key, event.id)}
          />
        </motion.div>
      ))}
    </div>
  )
}
