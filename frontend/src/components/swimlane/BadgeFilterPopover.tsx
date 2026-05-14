import { useEffect, useRef, useState } from 'react'
import {
  BadgeFilterKey,
  BadgeFilterMode,
  useSwimlaneStore,
} from '../../stores/useSwimlaneStore'

interface ChipDef {
  key: BadgeFilterKey
  label: string
}

interface GroupDef {
  label: string
  chips: ChipDef[]
}

const GROUPS: GroupDef[] = [
  {
    label: 'State',
    chips: [
      { key: 'state:open',   label: 'Open' },
      { key: 'state:closed', label: 'Closed' },
      { key: 'state:merged', label: 'Merged' },
    ],
  },
  {
    label: 'Draft',
    chips: [{ key: 'draft', label: 'Draft' }],
  },
  {
    label: 'Review',
    chips: [
      { key: 'review:approved',          label: '✓ Approved' },
      { key: 'review:changes_requested', label: '✗ Changes Requested' },
      { key: 'review:review_required',   label: '👀 Review Required' },
    ],
  },
  {
    label: 'CI',
    chips: [
      { key: 'ci:success', label: 'CI Passed' },
      { key: 'ci:failure', label: 'CI Failed' },
      { key: 'ci:pending', label: 'CI Running' },
    ],
  },
  {
    label: 'Review Score',
    chips: [
      { key: 'has_review', label: 'Has review' },
      { key: 'score:good', label: 'Score ≥ 7' },
      { key: 'score:ok',   label: 'Score 4–6' },
      { key: 'score:bad',  label: 'Score < 4' },
    ],
  },
  {
    label: 'Other',
    chips: [
      { key: 'new_commits',         label: 'New Commits' },
      { key: 'reviewers_requested', label: 'Reviewers Requested' },
      { key: 'followup',            label: 'Follow-up' },
    ],
  },
]

export function BadgeFilterPopover() {
  const badgeFilters = useSwimlaneStore((s) => s.badgeFilters)
  const mode = useSwimlaneStore((s) => s.badgeFilterMode)
  const toggle = useSwimlaneStore((s) => s.toggleBadgeFilter)
  const setMode = useSwimlaneStore((s) => s.setBadgeFilterMode)
  const clear = useSwimlaneStore((s) => s.clearBadgeFilters)

  const [open, setOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const activeCount = badgeFilters.size

  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (popoverRef.current?.contains(target)) return
      if (triggerRef.current?.contains(target)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const setModeHandler = (m: BadgeFilterMode) => () => setMode(m)

  return (
    <div className="mx-swl-badge-filter">
      <button
        ref={triggerRef}
        type="button"
        className={
          'mx-swl-badge-filter__trigger' +
          (activeCount > 0 ? ' mx-swl-badge-filter__trigger--active' : '') +
          (open ? ' mx-swl-badge-filter__trigger--open' : '')
        }
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Badge filters"
        data-tooltip="Filter cards by badge"
      >
        <span className="mx-swl-badge-filter__icon" aria-hidden="true">⛛</span>
        <span className="mx-swl-badge-filter__label">Filters</span>
        {activeCount > 0 && (
          <span className="mx-swl-badge-filter__count">{activeCount}</span>
        )}
      </button>

      {open && (
        <div ref={popoverRef} className="mx-swl-badge-filter__popover" role="dialog">
          <div className="mx-swl-badge-filter__mode-row">
            <span className="mx-swl-badge-filter__mode-label">Mode</span>
            <div className="mx-swl-badge-filter__mode-toggle" role="radiogroup" aria-label="Filter mode">
              <button
                type="button"
                role="radio"
                aria-checked={mode === 'OR'}
                className={
                  'mx-swl-badge-filter__mode-btn' +
                  (mode === 'OR' ? ' mx-swl-badge-filter__mode-btn--active' : '')
                }
                onClick={setModeHandler('OR')}
                data-tooltip="Match any selected badge"
              >
                OR
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={mode === 'AND'}
                className={
                  'mx-swl-badge-filter__mode-btn' +
                  (mode === 'AND' ? ' mx-swl-badge-filter__mode-btn--active' : '')
                }
                onClick={setModeHandler('AND')}
                data-tooltip="Match every dimension (multiple picks in one group are OR'd)"
              >
                AND
              </button>
            </div>
          </div>

          <div className="mx-swl-badge-filter__groups">
            {GROUPS.map((g) => (
              <div key={g.label} className="mx-swl-badge-filter__group">
                <div className="mx-swl-badge-filter__group-label">{g.label}</div>
                <div className="mx-swl-badge-filter__chips">
                  {g.chips.map(({ key, label }) => {
                    const on = badgeFilters.has(key)
                    return (
                      <button
                        key={key}
                        type="button"
                        className={
                          'mx-swl-badge-filter__chip' +
                          (on ? ' mx-swl-badge-filter__chip--on' : '')
                        }
                        onClick={() => toggle(key)}
                        aria-pressed={on}
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>

          <div className="mx-swl-badge-filter__footer">
            <button
              type="button"
              className="mx-swl-badge-filter__clear"
              onClick={clear}
              disabled={activeCount === 0}
            >
              Clear
            </button>
            <button
              type="button"
              className="mx-swl-badge-filter__done"
              onClick={() => setOpen(false)}
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
