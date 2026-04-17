import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { CommentedEvent } from '../../../api/types'

interface Props { event: CommentedEvent }

export function CommentBody({ event }: Props) {
  if (!event.body) return <em>(no content)</em>
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
      {event.body}
    </ReactMarkdown>
  )
}
