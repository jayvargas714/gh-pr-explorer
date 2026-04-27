import { SWIMLANE_COLORS, SwimlaneColor } from '../../api/types'

interface LaneColorPickerProps {
  value: SwimlaneColor
  onChange: (color: SwimlaneColor) => void
}

export function LaneColorPicker({ value, onChange }: LaneColorPickerProps) {
  return (
    <div className="mx-swl-color-picker" role="radiogroup" aria-label="Lane color">
      {SWIMLANE_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          role="radio"
          aria-checked={value === color}
          aria-label={color}
          className={`mx-swl-color-swatch mx-swl-color-swatch--${color}${
            value === color ? ' mx-swl-color-swatch--active' : ''
          }`}
          onClick={() => onChange(color)}
        />
      ))}
    </div>
  )
}
