interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  return (
    <div className={`mx-spinner mx-spinner--${size} ${className}`}>
      <div className="mx-spinner__circle"></div>
    </div>
  )
}
