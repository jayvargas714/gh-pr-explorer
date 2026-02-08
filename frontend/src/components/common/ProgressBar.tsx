interface ProgressBarProps {
  value: number // 0-100
  label?: string
  showPercentage?: boolean
  variant?: 'success' | 'error' | 'warning' | 'info'
}

export function ProgressBar({
  value,
  label,
  showPercentage = false,
  variant = 'info',
}: ProgressBarProps) {
  const clampedValue = Math.min(100, Math.max(0, value))

  return (
    <div className="mx-progress">
      {(label || showPercentage) && (
        <div className="mx-progress__header">
          {label && <span className="mx-progress__label">{label}</span>}
          {showPercentage && (
            <span className="mx-progress__percentage">{clampedValue.toFixed(0)}%</span>
          )}
        </div>
      )}
      <div className="mx-progress__track">
        <div
          className={`mx-progress__bar mx-progress__bar--${variant}`}
          style={{ width: `${clampedValue}%` }}
        />
      </div>
    </div>
  )
}
