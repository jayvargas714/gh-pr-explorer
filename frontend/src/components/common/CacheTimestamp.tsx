import { formatRelativeTime } from '../../utils/formatters'

interface CacheTimestampProps {
  lastUpdated: string | null
  stale?: boolean
  refreshing?: boolean
}

export function CacheTimestamp({ lastUpdated, stale, refreshing }: CacheTimestampProps) {
  if (!lastUpdated) return null

  const relativeTime = formatRelativeTime(lastUpdated)

  return (
    <span className={`mx-cache-timestamp ${stale ? 'mx-cache-timestamp--stale' : ''}`}>
      Updated {relativeTime}
      {stale && refreshing && ' \u00b7 refreshing\u2026'}
    </span>
  )
}
