import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import { getAuditDetail } from '../../api/audits'
import type { AuditDetail } from '../../api/types'
import { AuditChip } from './AuditChip'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

interface AuditViewerProps {
  auditId: number
  onClose: () => void
}

export function AuditViewer({ auditId, onClose }: AuditViewerProps) {
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getAuditDetail(auditId)
      .then((d) => {
        if (!cancelled) setAudit(d)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load audit')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [auditId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  const meta = audit?.content_json?.metadata

  return (
    <div className="mx-modal-overlay" onClick={onClose}>
      <div
        className="mx-draggable-modal mx-draggable-modal--xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-draggable-modal__header">
          <div className="mx-audit-viewer__header">
            <div>
              <h2>PB↔ED Audit{meta ? ` — PR #${meta.pr_number}` : ''}</h2>
              {meta && (meta.parent_pb?.id || (meta.eds && meta.eds.length > 0)) && (
                <div className="mx-audit-viewer__meta">
                  {meta.parent_pb?.id ? `Parent: ${meta.parent_pb.id}` : ''}
                  {meta.eds?.length
                    ? ` · EDs: ${meta.eds.map((e) => e.id).filter(Boolean).join(', ')}`
                    : ''}
                </div>
              )}
            </div>
            {audit && (
              <AuditChip
                findingCount={audit.finding_count}
                blockingCount={audit.blocking_count}
              />
            )}
          </div>
          <button
            className="mx-draggable-modal__close"
            onClick={onClose}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>
        <div className="mx-draggable-modal__body">
          {loading ? (
            <div className="mx-review-viewer__loading">
              <Spinner size="lg" />
              <p>Loading audit...</p>
            </div>
          ) : error ? (
            <Alert variant="error">{error}</Alert>
          ) : audit?.content ? (
            <div className="mx-audit-viewer__body mx-markdown-body">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
              >
                {audit.content}
              </ReactMarkdown>
            </div>
          ) : (
            <Alert variant="info">No audit content available.</Alert>
          )}
        </div>
      </div>
    </div>
  )
}
