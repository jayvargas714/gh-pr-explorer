import ReactMarkdown from 'react-markdown'
import { Modal } from '../common/Modal'
import { Badge } from '../common/Badge'
import type { PullRequest } from '../../api/types'

interface DescriptionModalProps {
  pr: PullRequest
  isOpen: boolean
  onClose: () => void
}

export function DescriptionModal({ pr, isOpen, onClose }: DescriptionModalProps) {
  if (!isOpen) return null

  return (
    <Modal title={`PR #${pr.number}: ${pr.title}`} onClose={onClose} size="lg">
      <div className="mx-description-modal">
        <div className="mx-description-modal__header">
          <div className="mx-description-modal__meta">
            <a
              href={pr.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mx-description-modal__link"
            >
              View on GitHub →
            </a>
            <span className="mx-description-modal__author">by {pr.author.login}</span>
          </div>

          <div className="mx-description-modal__badges">
            {pr.isDraft && <Badge variant="warning">Draft</Badge>}
            {pr.state === 'OPEN' && <Badge variant="success">Open</Badge>}
            {pr.state === 'CLOSED' && <Badge variant="neutral">Closed</Badge>}
            {pr.state === 'MERGED' && <Badge variant="info">Merged</Badge>}
          </div>
        </div>

        <div className="mx-description-modal__branches">
          <span className="mx-description-modal__branch">{pr.headRefName}</span>
          <span className="mx-description-modal__arrow">→</span>
          <span className="mx-description-modal__branch">{pr.baseRefName}</span>
        </div>

        <div className="mx-description-modal__content">
          {pr.body ? (
            <ReactMarkdown>{pr.body}</ReactMarkdown>
          ) : (
            <p className="mx-description-modal__empty">No description provided.</p>
          )}
        </div>

        {pr.labels && pr.labels.length > 0 && (
          <div className="mx-description-modal__labels">
            <strong>Labels:</strong>
            <div className="mx-description-modal__label-list">
              {pr.labels.map((label) => (
                <span
                  key={label.name}
                  className="mx-description-modal__label"
                  style={{ backgroundColor: `#${label.color}` }}
                >
                  {label.name}
                </span>
              ))}
            </div>
          </div>
        )}

        {pr.assignees && pr.assignees.length > 0 && (
          <div className="mx-description-modal__assignees">
            <strong>Assignees:</strong>
            <div className="mx-description-modal__assignee-list">
              {pr.assignees.map((assignee) => (
                <span key={assignee.login} className="mx-description-modal__assignee">
                  {assignee.login}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
