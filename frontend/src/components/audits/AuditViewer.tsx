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
import { Button } from '../common/Button'
import { VerdictModal } from '../queue/VerdictModal'

interface AuditViewerProps {
  auditId: number
  onClose: () => void
}

export function AuditViewer({ auditId, onClose }: AuditViewerProps) {
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showVerdict, setShowVerdict] = useState(false)

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
      if (e.key === 'Escape') {
        if (showVerdict) return // let the stacked VerdictModal own Escape
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose, showVerdict])

  const meta = audit?.content_json?.metadata

  // Derive owner/repo/PR for the verdict modal from the audit metadata,
  // falling back to the top-level audit record when metadata is absent.
  const repository = meta?.repository ?? audit?.repo ?? ''
  const prNumber = meta?.pr_number ?? audit?.pr_number
  const canPostVerdict =
    repository.includes('/') && typeof prNumber === 'number' && Number.isFinite(prNumber)

  return (
    <>
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
              <div className="mx-audit-viewer__header-actions">
                <AuditChip
                  findingCount={audit.finding_count}
                  blockingCount={audit.blocking_count}
                />
                {canPostVerdict && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setShowVerdict(true)}
                  >
                    Verdict
                  </Button>
                )}
              </div>
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

      {showVerdict && canPostVerdict && (
        <VerdictModal
          mode="audit"
          auditId={auditId}
          prNumber={prNumber as number}
          repo={repository}
          onClose={() => setShowVerdict(false)}
        />
      )}
    </>
  )
}
