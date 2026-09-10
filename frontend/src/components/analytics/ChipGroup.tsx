export interface ChipGroupProps<T extends string> {
  label?: string
  options: { value: T; label: string; disabled?: boolean; swatch?: string }[]
  selected: readonly T[]
  onToggle: (value: T) => void
}

export function ChipGroup<T extends string>({ label, options, selected, onToggle }: ChipGroupProps<T>) {
  return (
    <div className="mx-chip-group">
      {label && <label>{label}</label>}
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          disabled={option.disabled}
          className={`mx-button-group__item ${
            selected.includes(option.value) ? 'mx-button-group__item--active' : ''
          }`}
          onClick={() => onToggle(option.value)}
        >
          {option.swatch && <span className="mx-chip__swatch" style={{ background: option.swatch }} />}
          {option.label}
        </button>
      ))}
    </div>
  )
}
