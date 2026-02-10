import { ReactNode } from 'react'

interface BadgeProps {
  variant?: 'success' | 'error' | 'warning' | 'info' | 'neutral'
  size?: 'sm' | 'md'
  children: ReactNode
  className?: string
}

export function Badge({
  variant = 'neutral',
  size = 'md',
  children,
  className = '',
}: BadgeProps) {
  const classes = [
    'mx-badge',
    `mx-badge--${variant}`,
    `mx-badge--${size}`,
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return <span className={classes}>{children}</span>
}
