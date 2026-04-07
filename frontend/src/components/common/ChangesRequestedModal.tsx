import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Reviewer } from '../../api/types'

interface ChangesRequestedModalProps {
  reviewers: Reviewer[]
  onClose: () => void
}

const MIN_WIDTH = 360
const MIN_HEIGHT = 200

export function ChangesRequestedModal({ reviewers, onClose }: ChangesRequestedModalProps) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null)
  const nodeRef = useRef<HTMLDivElement>(null)

  const changesReviewers = reviewers.filter(
    (r) => r.state === 'CHANGES_REQUESTED' && r.body
  )

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleEscape)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [onClose])

  useEffect(() => {
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
  }, [])

  const onDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    const node = nodeRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    // Lock the size on first drag so it doesn't expand when switching to fixed
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
          <h2>Changes Requested</h2>
          <button
            className="mx-draggable-modal__close"
            onClick={onClose}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>
        <div className="mx-draggable-modal__body">
          <div className="mx-changes-requested-modal">
            {changesReviewers.length === 0 ? (
              <p className="mx-changes-requested-modal__empty">
                No comment provided with the review.
              </p>
            ) : (
              changesReviewers.map((r) => (
                <div key={r.login} className="mx-changes-requested-modal__entry">
                  <div className="mx-changes-requested-modal__reviewer">
                    <img
                      src={r.avatarUrl || `https://github.com/${r.login}.png?size=40`}
                      alt={r.login}
                      className="mx-changes-requested-modal__avatar"
                    />
                    <span className="mx-changes-requested-modal__name">{r.login}</span>
                  </div>
                  <div className="mx-changes-requested-modal__body mx-markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {r.body!}
                    </ReactMarkdown>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
        <div className="mx-draggable-modal__resize-handle" onMouseDown={onResizeStart} />
      </div>
    </div>
  )
}
