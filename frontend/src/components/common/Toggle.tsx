interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  disabled?: boolean
}

export function Toggle({ checked, onChange, label, disabled = false }: ToggleProps) {
  return (
    <label className={`mx-toggle ${disabled ? 'mx-toggle--disabled' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="mx-toggle__input"
      />
      <span className="mx-toggle__slider"></span>
      {label && <span className="mx-toggle__label">{label}</span>}
    </label>
  )
}
