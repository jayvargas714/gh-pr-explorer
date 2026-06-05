import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import { getAuditDetail, postAuditInlineComments } from '../../api/audits'
import { APIError } from '../../api/client'
import type { AuditDetail, AuditJSON } from '../../api/types'
import { AuditChip } from './AuditChip'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'
import { VerdictModal } from '../queue/VerdictModal'

interface AuditViewerProps {
  auditId: number
  onClose: () => void
}

/**
 * Count findings that carry a resolvable file+line location. Uses the SAME
 * predicate as the backend `_findings_to_inline_comments` (isinstance(line, int))
 * and the verdict-path `auditInlineComments`: a location with a non-empty file
 * and an integer line >= 1.
 */
function mappableFindingCount(content: AuditJSON | null | undefined): number {
  if (!content) return 0
  let count = 0
  for (const section of content.audits || []) {
    for (const f of section.findings || []) {
      const loc = (f.locations || []).find(
        (l) => l.file && Number.isInteger(l.line) && (l.line as number) >= 1,
      )
      if (loc) count += 1
    }
  }
  return count
}

export function AuditViewer({ auditId, onClose }: AuditViewerProps) {
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showVerdict, setShowVerdict] = useState(false)
  const [posting, setPosting] = useState(false)
  const [postMessage, setPostMessage] = useState<string | null>(null)

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

  const mappableCount = useMemo(
    () => mappableFindingCount(audit?.content_json),
    [audit?.content_json],
  )
  const inlinePosted = !!audit?.inline_comments_posted
  const canPostInline = canPostVerdict && mappableCount > 0

  const handlePostInline = async () => {
    if (posting || inlinePosted || !canPostInline) return
    setPosting(true)
    setPostMessage(null)
    try {
      const resp = await postAuditInlineComments(auditId)
      // Re-fetch so inline_comments_posted reflects the authoritative server state.
      const refreshed = await getAuditDetail(auditId).catch(() => null)
      if (refreshed) setAudit(refreshed)
      setPostMessage(resp.message || 'Inline comments posted')
    } catch (e) {
      if (e instanceof APIError && e.status === 409) {
        // Already posted on the server — sync local state to reflect it.
        const refreshed = await getAuditDetail(auditId).catch(() => null)
        if (refreshed) setAudit(refreshed)
        setPostMessage(e.message || 'Inline comments already posted for this audit')
      } else {
        setPostMessage(
          e instanceof Error ? e.message : 'Failed to post inline comments',
        )
      }
    } finally {
      setPosting(false)
    }
  }

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
                {canPostInline && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handlePostInline}
                    disabled={posting || inlinePosted}
                    data-tooltip={
                      inlinePosted
                        ? 'Inline comments already posted to GitHub'
                        : `Post ${mappableCount} finding(s) with file+line as inline comments`
                    }
                  >
                    {inlinePosted ? (
                      '✓ Inline comments posted'
                    ) : posting ? (
                      <><Spinner size="sm" /> Posting…</>
                    ) : (
                      'Post inline comments'
                    )}
                  </Button>
                )}
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
          {postMessage && (
            <Alert variant="info">{postMessage}</Alert>
          )}
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
