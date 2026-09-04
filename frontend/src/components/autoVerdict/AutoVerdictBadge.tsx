import { Badge } from '../common/Badge'
import { AutoVerdictRecord } from '../../api/types'
import { formatLocalDateTime } from '../queue/RevLogBadge'

interface AutoVerdictBadgeProps {
  record: AutoVerdictRecord
}

type Variant = 'success' | 'error' | 'warning' | 'info' | 'neutral'

/** Badge label + variant for a recorded auto verdict. */
export function describeAutoVerdict(record: AutoVerdictRecord): { label: string; variant: Variant } {
  if (record.outcome === 'posted') {
    switch (record.event) {
      case 'REQUEST_CHANGES':
        return { label: '🤖 auto ✗ changes requested', variant: 'error' }
      case 'APPROVE':
        return { label: '🤖 auto ✓ approved', variant: 'success' }
      case 'COMMENT':
        return { label: '🤖 auto 💬 comment', variant: 'info' }
      default:
        return { label: '🤖 auto verdict posted', variant: 'info' }
    }
  }
  switch (record.outcome) {
    case 'suppressed':
      return { label: '🤖 passed — approve manually', variant: 'warning' }
    case 'error':
      return { label: '🤖 auto verdict failed', variant: 'error' }
    case 'deferred':
      return { label: '🤖 rate limited — will retry', variant: 'warning' }
    case 'mediation':
      return { label: '🤖 locked — human mediation', variant: 'error' }
    case 'pending':
      return { label: '🤖 auto verdict running', variant: 'neutral' }
    default:
      return { label: '🤖 auto skipped', variant: 'neutral' }
  }
}

export function AutoVerdictBadge({ record }: AutoVerdictBadgeProps) {
  const { label, variant } = describeAutoVerdict(record)

  const setAside =
    record.disputedCount != null || record.deferredCount != null
      ? ` / ${record.disputedCount ?? 0} disputed / ${record.deferredCount ?? 0} deferred`
      : ''
  const tallies =
    record.criticalCount !== null
      ? `${record.criticalCount} critical / ${record.majorCount} major / ${record.minorCount} minor${setAside}`
      : null

  const tooltip = [
    record.reason,
    tallies,
    record.createdAt ? formatLocalDateTime(record.createdAt) : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <span data-tooltip={tooltip || undefined}>
      <Badge variant={variant} size="sm">
        {label}
      </Badge>
    </span>
  )
}
