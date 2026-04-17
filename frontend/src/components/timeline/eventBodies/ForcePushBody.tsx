import type { ForcePushedEvent } from '../../../api/types'

interface Props { event: ForcePushedEvent }

export function ForcePushBody({ event }: Props) {
  return (
    <div>
      Force-pushed{' '}
      <code>{event.before ? event.before.slice(0, 7) : '—'}</code>
      {' → '}
      <code>{event.after ? event.after.slice(0, 7) : '—'}</code>
    </div>
  )
}
