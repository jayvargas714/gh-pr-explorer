import { useState } from 'react'

interface ChipListEditorProps {
  values: string[]
  onChange: (values: string[]) => void
  placeholder: string
  disabled?: boolean
  // Mono chips for globs/repos, regular for author names.
  mono?: boolean
}

/** Editable chip list: type a value, Enter/Add appends, × removes. */
export function ChipListEditor({ values, onChange, placeholder, disabled, mono }: ChipListEditorProps) {
  const [input, setInput] = useState('')

  const add = () => {
    const value = input.trim()
    if (!value || values.includes(value)) {
      setInput('')
      return
    }
    onChange([...values, value])
    setInput('')
  }

  return (
    <div className="mx-chip-editor">
      <div className="mx-chip-editor__chips">
        {values.map((value) => (
          <span key={value} className={`mx-chip-editor__chip ${mono ? 'mx-chip-editor__chip--mono' : ''}`}>
            {value}
            <button
              type="button"
              className="mx-chip-editor__remove"
              onClick={() => onChange(values.filter((v) => v !== value))}
              disabled={disabled}
              aria-label={`Remove ${value}`}
            >
              ×
            </button>
          </span>
        ))}
        {values.length === 0 && <span className="mx-chip-editor__empty">none</span>}
      </div>
      <div className="mx-chip-editor__input-row">
        <input
          type="text"
          className="mx-input mx-chip-editor__input"
          value={input}
          placeholder={placeholder}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          disabled={disabled}
        />
        <button type="button" className="mx-button mx-button--ghost mx-button--sm" onClick={add} disabled={disabled}>
          Add
        </button>
      </div>
    </div>
  )
}
