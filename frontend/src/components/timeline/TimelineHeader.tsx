import { useTimelineStore, timelineKey } from '../../stores/useTimelineStore'

interface Props {
  owner: string
  repo: string
  prNumber: number
  title: string
  url: string
}

function formatAgo(iso: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return ''
  const diff = Math.max(0, (Date.now() - t) / 1000)
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function TimelineHeader({ owner, repo, prNumber, title, url }: Props) {
  const key = timelineKey(owner, repo, prNumber)
  const entry = useTimelineStore((s) => s.timelines[key])
  const load = useTimelineStore((s) => s.load)
  const close = useTimelineStore((s) => s.close)

  return (
    <div className="tl-modal__header">
      <a className="tl-modal__title" href={url} target="_blank" rel="noopener noreferrer">
        #{prNumber} {title}
      </a>
      <div className="tl-modal__actions">
        {entry?.lastUpdated && (
          <span className={`tl-updated${entry.refreshing ? ' tl-updated--refreshing' : ''}`}>
            Updated {formatAgo(entry.lastUpdated)}{entry.refreshing ? ' · refreshing…' : ''}
          </span>
        )}
        <button
          type="button"
          onClick={() => load(owner, repo, prNumber, { force: true })}
          aria-label="Refresh timeline"
          style={{ background: 'transparent', border: '1px solid var(--mx-border, #2a2a2a)',
                   color: 'var(--mx-text, #e5e7eb)', borderRadius: 8, padding: '6px 10px',
                   cursor: 'pointer' }}
        >
          ↻ Refresh
        </button>
        <button
          type="button"
          onClick={close}
          aria-label="Close timeline"
          style={{ background: 'transparent', border: 'none', color: 'var(--mx-text, #e5e7eb)',
                   fontSize: 20, cursor: 'pointer', padding: '0 8px' }}
        >
          ×
        </button>
      </div>
    </div>
  )
}
