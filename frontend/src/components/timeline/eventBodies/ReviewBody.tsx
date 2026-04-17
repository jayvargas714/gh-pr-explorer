import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { ReviewedEvent } from '../../../api/types'

interface Props { event: ReviewedEvent }

const STATE_LABEL: Record<ReviewedEvent['state'], string> = {
  APPROVED: 'Approved',
  CHANGES_REQUESTED: 'Changes requested',
  COMMENTED: 'Commented',
}

export function ReviewBody({ event }: Props) {
  return (
    <div>
      <div style={{ marginBottom: 10, fontWeight: 500 }}>
        {STATE_LABEL[event.state] ?? event.state}
      </div>
      {event.body
        ? <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
            {event.body}
          </ReactMarkdown>
        : <em style={{ color: 'var(--mx-text-muted, #888)' }}>(no body)</em>}
    </div>
  )
}
