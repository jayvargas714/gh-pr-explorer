import { Badge } from './Badge'
import { behindVariant } from '../../utils/prActions'

interface BehindBadgeProps {
  /** Commits behind base; null/undefined (not computed yet) renders nothing. */
  behindBy: number | null | undefined
  size?: 'sm' | 'md'
}

/** "✓ Up to date" / "⚠ N behind", shared by PR list, board, queue and pipeline. */
export function BehindBadge({ behindBy, size = 'md' }: BehindBadgeProps) {
  if (behindBy === null || behindBy === undefined) return null
  return (
    <Badge variant={behindVariant(behindBy)} size={size}>
      {behindBy === 0 ? '✓ Up to date' : `⚠ ${behindBy} behind`}
    </Badge>
  )
}
