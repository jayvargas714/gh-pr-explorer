import type { ReviewRequestedEvent } from '../../../api/types'

interface Props { event: ReviewRequestedEvent }

export function ReviewRequestedBody({ event }: Props) {
  const reviewer = event.requested_reviewer
  if (!reviewer) return <div>Review requested</div>
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <img src={reviewer.avatar_url} alt={reviewer.login} width={20} height={20}
           style={{ borderRadius: '50%' }} />
      <span>Requested review from <strong>{reviewer.login}</strong></span>
    </div>
  )
}
