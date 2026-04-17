import type { CommittedEvent } from '../../../api/types'

interface Props { event: CommittedEvent }

export function CommitBody({ event }: Props) {
  return (
    <div>
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{event.message}</pre>
      <div style={{ marginTop: 8 }}>
        <code>{event.short_sha}</code>
      </div>
    </div>
  )
}
