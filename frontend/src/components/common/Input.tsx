import { InputHTMLAttributes, forwardRef } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = '', ...props }, ref) => {
    return (
      <div className="mx-input-wrapper">
        {label && <label className="mx-input-label">{label}</label>}
        <input
          ref={ref}
          className={`mx-input ${error ? 'mx-input--error' : ''} ${className}`}
          {...props}
        />
        {error && <span className="mx-input-error">{error}</span>}
      </div>
    )
  }
)

Input.displayName = 'Input'
