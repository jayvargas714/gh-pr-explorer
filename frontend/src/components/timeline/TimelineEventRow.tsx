import { motion, AnimatePresence } from 'framer-motion'
import type { TimelineEvent, TimelineEventType } from '../../api/types'
import { CommitBody } from './eventBodies/CommitBody'
import { CommentBody } from './eventBodies/CommentBody'
import { ReviewBody } from './eventBodies/ReviewBody'
import { StateChangeBody } from './eventBodies/StateChangeBody'
import { ReviewRequestedBody } from './eventBodies/ReviewRequestedBody'
import { ForcePushBody } from './eventBodies/ForcePushBody'

interface Props {
  event: TimelineEvent
  expanded: boolean
  onToggle: () => void
}

interface StyleVars extends React.CSSProperties {
  ['--tl-dot-color']?: string
  ['--tl-dot-glow']?: string
}

const DOT_COLOR: Record<TimelineEventType, string> = {
  opened: '#6366f1',
  committed: '#10b981',
  commented: '#f59e0b',
  reviewed: '#f59e0b',
  review_requested: '#94a3b8',
  ready_for_review: '#0ea5e9',
  convert_to_draft: '#0ea5e9',
  closed: '#ef4444',
  reopened: '#6366f1',
  merged: '#8b5cf6',
  head_ref_force_pushed: '#f59e0b',
}

function dotColorFor(event: TimelineEvent): string {
  if (event.type === 'reviewed') {
    if (event.state === 'APPROVED') return '#10b981'
    if (event.state === 'CHANGES_REQUESTED') return '#ef4444'
    return '#f59e0b'
  }
  return DOT_COLOR[event.type]
}

function glowFor(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, 0.22)`
}

function formatWhen(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function renderHeader(event: TimelineEvent): string {
  const who = event.actor?.login || 'unknown'
  switch (event.type) {
    case 'opened': return `${who} opened this pull request`
    case 'committed': return `${who} committed`
    case 'commented': return `${who} commented`
    case 'reviewed': {
      if (event.state === 'APPROVED') return `${who} approved`
      if (event.state === 'CHANGES_REQUESTED') return `${who} requested changes`
      return `${who} reviewed`
    }
    case 'review_requested': return `${who} requested a review`
    case 'ready_for_review': return `${who} marked ready for review`
    case 'convert_to_draft': return `${who} converted to draft`
    case 'closed': return `${who} closed this pull request`
    case 'reopened': return `${who} reopened this pull request`
    case 'merged': return `${who} merged this pull request`
    case 'head_ref_force_pushed': return `${who} force-pushed`
  }
}

function renderBody(event: TimelineEvent) {
  switch (event.type) {
    case 'committed': return <CommitBody event={event} />
    case 'commented': return <CommentBody event={event} />
    case 'reviewed': return <ReviewBody event={event} />
    case 'review_requested': return <ReviewRequestedBody event={event} />
    case 'head_ref_force_pushed': return <ForcePushBody event={event} />
    case 'opened':
    case 'closed':
    case 'reopened':
    case 'merged':
    case 'ready_for_review':
    case 'convert_to_draft':
      return <StateChangeBody event={event} />
  }
}

export function TimelineEventRow({ event, expanded, onToggle }: Props) {
  const color = dotColorFor(event)
  const styleVars: StyleVars = {
    '--tl-dot-color': color,
    '--tl-dot-glow': glowFor(color),
  }

  return (
    <div className="tl-event" style={styleVars}>
      <span
        className="tl-event__dot"
        onClick={onToggle}
        role="button"
        aria-label={expanded ? 'Collapse event' : 'Expand event'}
      />
      <motion.div
        layout
        className={`tl-event__card${expanded ? ' tl-event__card--expanded' : ''}`}
      >
        <button
          type="button"
          className="tl-event__header"
          onClick={onToggle}
          aria-expanded={expanded}
        >
          <span className="tl-event__who">
            {event.actor?.avatar_url && (
              <img className="tl-event__avatar" src={event.actor.avatar_url} alt="" />
            )}
            <span>{renderHeader(event)}</span>
          </span>
          <span className="tl-event__when">{formatWhen(event.created_at)}</span>
        </button>
        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              className="tl-event__body"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ type: 'spring', damping: 26, stiffness: 300 }}
            >
              {renderBody(event)}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
