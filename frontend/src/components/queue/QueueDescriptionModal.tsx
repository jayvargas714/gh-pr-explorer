import { useEffect, useState } from 'react'
import { fetchPRDetails } from '../../api/prs'
import type { PullRequest } from '../../api/types'
import { DescriptionModal } from '../modals/DescriptionModal'

interface QueueDescriptionModalProps {
  owner: string
  repo: string
  prNumber: number
  prTitle: string
  isOpen: boolean
  onClose: () => void
}

export function QueueDescriptionModal({
  owner,
  repo,
  prNumber,
  prTitle,
  isOpen,
  onClose,
}: QueueDescriptionModalProps) {
  const [pr, setPR] = useState<PullRequest | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setPR(null)
    fetchPRDetails(owner, repo, prNumber)
      .then((result) => {
        if (cancelled) return
        if (!result) {
          setError('PR not found.')
        } else {
          setPR(result)
        }
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load PR description.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isOpen, owner, repo, prNumber])

  useEffect(() => {
    if (!isOpen) return
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isOpen, onClose])

  if (!isOpen) return null

  if (pr) {
    return <DescriptionModal pr={pr} isOpen={isOpen} onClose={onClose} />
  }

  return (
    <div className="mx-modal-overlay" onClick={onClose}>
      <div
        className="mx-draggable-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-draggable-modal__header">
          <h2>PR #{prNumber}: {prTitle}</h2>
          <button
            className="mx-draggable-modal__close"
            onClick={onClose}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>
        <div className="mx-draggable-modal__body">
          <div className="mx-description-modal">
            {loading && <p className="mx-description-modal__empty">Loading description…</p>}
            {error && <p className="mx-description-modal__empty">{error}</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
