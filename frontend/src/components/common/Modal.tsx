import { ReactNode, useEffect } from 'react'

interface ModalProps {
  isOpen?: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl'
}

export function Modal({
  isOpen = true,
  onClose,
  title,
  children,
  size = 'md',
}: ModalProps) {
  // Close on Escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) {
      document.addEventListener('keydown', handleEscape)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="mx-modal-overlay" onClick={onClose}>
      <div
        className={`mx-modal mx-modal--${size}`}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="mx-modal__header">
            <h2>{title}</h2>
            <button
              className="mx-modal__close"
              onClick={onClose}
              aria-label="Close modal"
            >
              ×
            </button>
          </div>
        )}
        <div className="mx-modal__body">{children}</div>
      </div>
    </div>
  )
}
