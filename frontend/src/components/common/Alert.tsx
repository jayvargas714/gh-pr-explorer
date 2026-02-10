import { ReactNode } from 'react'

interface AlertProps {
  variant?: 'success' | 'error' | 'warning' | 'info'
  children: ReactNode
  onClose?: () => void
}

export function Alert({ variant = 'info', children, onClose }: AlertProps) {
  return (
    <div className={`mx-alert mx-alert--${variant}`}>
      <div className="mx-alert__content">{children}</div>
      {onClose && (
        <button className="mx-alert__close" onClick={onClose}>
          ×
        </button>
      )}
    </div>
  )
}
