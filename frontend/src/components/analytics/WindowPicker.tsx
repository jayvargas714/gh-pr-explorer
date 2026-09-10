import { ChipGroup } from './ChipGroup'
import { Input } from '../common/Input'
import { Select } from '../common/Select'
import { CacheTimestamp } from '../common/CacheTimestamp'
import { Spinner } from '../common/Spinner'
import { AnalyticsWindow, WINDOW_PRESETS, utcDateString } from '../../utils/analyticsSeries'

interface WindowPickerProps {
  window: AnalyticsWindow
  onWindowChange: (w: AnalyticsWindow) => void
  base: string
  baseOptions: string[]
  onBaseChange: (base: string) => void
  rangeError: string | null
  lastUpdated: string | null
  syncing: boolean
  refreshing: boolean
  earliest?: string | null
  resolvedFrom?: string | null
  resolvedTo?: string | null
}

export function WindowPicker({
  window,
  onWindowChange,
  base,
  baseOptions,
  onBaseChange,
  rangeError,
  lastUpdated,
  syncing,
  refreshing,
  earliest,
  resolvedFrom,
  resolvedTo,
}: WindowPickerProps) {
  const today = utcDateString(new Date())
  const baseSelectOptions = (baseOptions.length > 0 ? baseOptions : [base]).map((b) => ({
    value: b,
    label: b,
  }))

  return (
    <div className="mx-window-picker">
      <ChipGroup
        options={WINDOW_PRESETS}
        selected={[window.preset]}
        onToggle={(preset) => onWindowChange({ preset, from: '', to: '' })}
      />

      <div className="mx-date-range">
        <Input
          type="date"
          placeholder="From"
          max={today}
          min={earliest ?? undefined}
          value={window.from}
          onChange={(e) => onWindowChange({ preset: 'custom', from: e.target.value, to: window.to })}
        />
        <span className="mx-date-range__sep">to</span>
        <Input
          type="date"
          placeholder="To"
          max={today}
          min={earliest ?? undefined}
          value={window.to}
          onChange={(e) => onWindowChange({ preset: 'custom', from: window.from, to: e.target.value })}
        />
      </div>
      {rangeError && <span className="mx-window-picker__error">{rangeError}</span>}

      <Select label="Base" options={baseSelectOptions} value={base} onChange={(e) => onBaseChange(e.target.value)} />

      <div className="mx-window-picker__status">
        {resolvedFrom && resolvedTo && (
          <span className="mx-window-picker__range">{resolvedFrom} &rarr; {resolvedTo}</span>
        )}
        <CacheTimestamp lastUpdated={lastUpdated} stale={syncing} refreshing={syncing} />
        {syncing && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Spinner size="sm" /> Syncing&hellip;
          </span>
        )}
        {refreshing && <Spinner size="sm" />}
      </div>
    </div>
  )
}
