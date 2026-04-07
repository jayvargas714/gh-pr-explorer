import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Badge } from '../common/Badge'
import type { PullRequest } from '../../api/types'

interface DescriptionModalProps {
  pr: PullRequest
  isOpen: boolean
  onClose: () => void
}

const MIN_WIDTH = 400
const MIN_HEIGHT = 300

export function DescriptionModal({ pr, isOpen, onClose }: DescriptionModalProps) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null)
  const nodeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) return
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleEscape)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [isOpen, onClose])

  useEffect(() => {
    if (!isOpen) return
    const handleMouseMove = (e: MouseEvent) => {
      if (dragRef.current) {
        e.preventDefault()
        const dx = e.clientX - dragRef.current.startX
        const dy = e.clientY - dragRef.current.startY
        setPos({
          x: Math.max(0, dragRef.current.origX + dx),
          y: Math.max(0, dragRef.current.origY + dy),
        })
      }
      if (resizeRef.current) {
        e.preventDefault()
        const dx = e.clientX - resizeRef.current.startX
        const dy = e.clientY - resizeRef.current.startY
        setSize({
          w: Math.max(MIN_WIDTH, resizeRef.current.origW + dx),
          h: Math.max(MIN_HEIGHT, resizeRef.current.origH + dy),
        })
      }
    }
    const handleMouseUp = () => {
      dragRef.current = null
      resizeRef.current = null
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isOpen])

  const onDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    const node = nodeRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    if (!size) {
      setSize({ w: rect.width, h: rect.height })
    }
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: pos?.x ?? rect.left,
      origY: pos?.y ?? rect.top,
    }
  }, [pos, size])

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const node = nodeRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    // Pin position on first resize so switching to fixed doesn't jump the modal
    if (!pos) {
      setPos({ x: rect.left, y: rect.top })
    }
    if (!size) {
      setSize({ w: rect.width, h: rect.height })
    }
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origW: size?.w ?? rect.width,
      origH: size?.h ?? rect.height,
    }
  }, [pos, size])

  if (!isOpen) return null

  const modalStyle: React.CSSProperties = {
    ...(pos ? { left: pos.x, top: pos.y } : {}),
    ...(size ? { width: size.w, height: size.h } : {}),
  }

  return (
    <div className="mx-modal-overlay" onClick={onClose}>
      <div
        ref={nodeRef}
        className={`mx-draggable-modal${pos ? ' mx-draggable-modal--positioned' : ''}`}
        style={modalStyle}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-draggable-modal__header" onMouseDown={onDragStart}>
          <h2>PR #{pr.number}: {pr.title}</h2>
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

            <div className="mx-description-modal__content mx-markdown-body">
              {pr.body ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {pr.body}
                </ReactMarkdown>
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
        </div>
        <div className="mx-draggable-modal__resize-handle" onMouseDown={onResizeStart} />
      </div>
    </div>
  )
}
