import { useState, useEffect } from 'react'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { Alert } from '../common/Alert'
import { Spinner } from '../common/Spinner'
import { fetchSectionIssues, postInlineComments } from '../../api/reviews'
import type { SectionIssuePreview } from '../../api/types'

const SECTION_LABELS: Record<string, string> = {
  critical: 'Critical Issues',
  major: 'Major Concerns',
  minor: 'Minor Issues',
}

interface InlineIssuePickerModalProps {
  reviewId: number
  section: string
  onClose: () => void
  onPosted: () => void
}

export function InlineIssuePickerModal({
  reviewId,
  section,
  onClose,
  onPosted,
}: InlineIssuePickerModalProps) {
  const [issues, setIssues] = useState<SectionIssuePreview[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadIssues()
  }, [reviewId, section])

  const loadIssues = async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await fetchSectionIssues(reviewId, section)
      setIssues(result.issues)
      // Select all by default
      setSelected(new Set(result.issues.map((i) => i.index)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load issues')
    } finally {
      setLoading(false)
    }
  }

  const toggleIssue = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === issues.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(issues.map((i) => i.index)))
    }
  }

  const handlePost = async () => {
    if (selected.size === 0) return
    try {
      setPosting(true)
      setError(null)
      await postInlineComments(reviewId, section, Array.from(selected))
      onPosted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to post comments')
    } finally {
      setPosting(false)
    }
  }

  const formatLocation = (issue: SectionIssuePreview) => {
    if (!issue.path) return ''
    let loc = issue.path
    if (issue.start_line != null && issue.end_line != null && issue.start_line !== issue.end_line) {
      loc += `:${issue.start_line}-${issue.end_line}`
    } else if (issue.start_line != null) {
      loc += `:${issue.start_line}`
    }
    return loc
  }

  const heading = SECTION_LABELS[section] || section

  return (
    <Modal title={`Post ${heading}`} onClose={onClose} size="lg">
      {loading ? (
        <div className="mx-issue-picker__loading">
          <Spinner size="md" />
          <p>Loading issues...</p>
        </div>
      ) : (
        <>
          {error && <Alert variant="error">{error}</Alert>}

          {issues.length === 0 ? (
            <Alert variant="info">No issues found in this section.</Alert>
          ) : (
            <>
              <div className="mx-issue-picker__toolbar">
                <label className="mx-issue-picker__select-all">
                  <input
                    type="checkbox"
                    checked={selected.size === issues.length}
                    ref={(el) => {
                      if (el) el.indeterminate = selected.size > 0 && selected.size < issues.length
                    }}
                    onChange={toggleAll}
                    disabled={posting}
                  />
                  Select All ({selected.size}/{issues.length})
                </label>
              </div>

              <div className="mx-issue-picker__list">
                {issues.map((issue) => (
                  <label
                    key={issue.index}
                    className={`mx-issue-picker__item${selected.has(issue.index) ? ' mx-issue-picker__item--selected' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(issue.index)}
                      onChange={() => toggleIssue(issue.index)}
                      disabled={posting}
                    />
                    <div className="mx-issue-picker__item-content">
                      <div className="mx-issue-picker__item-title">{issue.title}</div>
                      {issue.path && (
                        <code className="mx-issue-picker__item-location">
                          {formatLocation(issue)}
                        </code>
                      )}
                    </div>
                  </label>
                ))}
              </div>
            </>
          )}

          <div className="mx-issue-picker__actions">
            <Button variant="ghost" onClick={onClose} disabled={posting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handlePost}
              disabled={posting || selected.size === 0}
            >
              {posting ? 'Posting...' : `Post ${selected.size} Issue${selected.size !== 1 ? 's' : ''}`}
            </Button>
          </div>
        </>
      )}
    </Modal>
  )
}
