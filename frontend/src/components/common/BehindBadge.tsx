import { Badge } from './Badge'
import { behindAgeVariant, behindHours, behindVariant, formatBehindAge } from '../../utils/prActions'

interface BehindBadgeProps {
  /** Commits behind base; null/undefined (not computed yet) renders nothing. */
  behindBy: number | null | undefined
  /** Committer date of the oldest base commit the branch lacks; adds a time badge. */
  behindSince?: string | null
  size?: 'sm' | 'md'
}

/** "✓ Up to date" / "⚠ N behind" plus a "⏱ 49h" time-behind badge, shared by
 * PR list, board, queue and pipeline. */
export function BehindBadge({ behindBy, behindSince, size = 'md' }: BehindBadgeProps) {
  if (behindBy === null || behindBy === undefined) return null
  const hours = behindBy > 0 && behindSince ? behindHours(behindSince) : null
  return (
    <span className="mx-behind-badges">
      <Badge variant={behindVariant(behindBy)} size={size}>
        {behindBy === 0 ? '✓ Up to date' : `⚠ ${behindBy} behind`}
      </Badge>
      {hours !== null && (
        <span title={`Base has had commits this branch lacks since ${new Date(behindSince!).toLocaleString()}`}>
          <Badge variant={behindAgeVariant(hours)} size={size}>
            ⏱ {formatBehindAge(hours)}
          </Badge>
        </span>
      )}
    </span>
  )
}
