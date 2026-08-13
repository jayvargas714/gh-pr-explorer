import { useEffect, useRef, useState } from 'react'
import { setCardAutoVerdict } from '../../api/autoVerdict'
import { AutoVerdictReviewer, MergeQueueItem } from '../../api/types'
import { describeCriteria, useAutoVerdictStore } from '../../stores/useAutoVerdictStore'
import { AutoVerdictConfigModal } from './AutoVerdictConfigModal'

interface AutoVerdictToggleProps {
  item: MergeQueueItem
  onRefresh: () => void
}

const REVIEWERS: { key: AutoVerdictReviewer; label: string; agent: string }[] = [
  { key: 'default', label: 'Default Reviewer', agent: 'elite-code-reviewer' },
  { key: 'pb', label: 'Product Brief Reviewer', agent: 'product-brief-reviewer' },
  { key: 'ed', label: 'Engineering Design Reviewer', agent: 'ed-reviewer' },
]

export function AutoVerdictToggle({ item, onRefresh }: AutoVerdictToggleProps) {
  const armed = item.autoVerdict?.enabled ?? false
  const reviewerType = item.autoVerdict?.reviewerType ?? 'default'
  const config = useAutoVerdictStore((s) => s.config)

  const [menuOpen, setMenuOpen] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [menuOpen])

  const persist = async (enabled: boolean, reviewer: AutoVerdictReviewer) => {
    setBusy(true)
    try {
      await setCardAutoVerdict(item.number, item.repo, { enabled, reviewerType: reviewer })
      onRefresh()
    } catch (err) {
      console.error('Failed to update auto verdict:', err)
    } finally {
      setBusy(false)
    }
  }

  const tooltip = armed
    ? `Auto verdict armed (${REVIEWERS.find((r) => r.key === reviewerType)?.label}) — ${describeCriteria(config)}`
    : 'Arm auto verdict: the next completed review posts its verdict automatically'

  // dnd-kit's PointerSensor would otherwise steal these gestures on swimlane cards.
  const stopDrag = (e: React.SyntheticEvent) => e.stopPropagation()

  return (
    <>
      <div className="mx-auto-verdict__wrapper" ref={wrapperRef}>
        <button
          type="button"
          className={`mx-button mx-button--ghost mx-button--sm mx-auto-verdict-btn${armed ? ' mx-auto-verdict-btn--active' : ''}`}
          aria-pressed={armed}
          disabled={busy}
          data-tooltip={tooltip}
          onPointerDown={stopDrag}
          onClick={(e) => {
            stopDrag(e)
            setMenuOpen(!menuOpen)
          }}
        >
          🤖 Auto{armed ? ' ✓' : ''}
        </button>

        {menuOpen && (
          <div
            className="mx-auto-verdict-menu"
            role="dialog"
            aria-label="Auto verdict settings"
            onPointerDown={stopDrag}
            onClick={stopDrag}
          >
            <button
              type="button"
              className={`mx-auto-verdict-menu__arm${armed ? ' mx-auto-verdict-menu__arm--active' : ''}`}
              disabled={busy}
              onClick={() => {
                persist(!armed, reviewerType)
                setMenuOpen(false)
              }}
            >
              {armed ? '⏹ Disarm auto verdict' : '▶ Arm auto verdict'}
            </button>

            <div className="mx-auto-verdict-menu__section">
              <span className="mx-auto-verdict-menu__label">Review agent</span>
              <div role="radiogroup" aria-label="Reviewer agent">
                {REVIEWERS.map(({ key, label, agent }) => (
                  <button
                    key={key}
                    type="button"
                    role="radio"
                    aria-checked={reviewerType === key}
                    className={`mx-auto-verdict-menu__reviewer${reviewerType === key ? ' mx-auto-verdict-menu__reviewer--active' : ''}`}
                    disabled={busy}
                    onClick={() => persist(armed, key)}
                  >
                    <strong>{label}</strong>
                    <small>{agent}</small>
                  </button>
                ))}
              </div>
            </div>

            <div className="mx-auto-verdict-menu__section">
              <span className="mx-auto-verdict-menu__criteria">{describeCriteria(config)}</span>
              <button
                type="button"
                className="mx-auto-verdict-menu__link"
                onClick={() => {
                  setMenuOpen(false)
                  setConfigOpen(true)
                }}
              >
                Edit criteria…
              </button>
            </div>
          </div>
        )}
      </div>

      {configOpen && <AutoVerdictConfigModal onClose={() => setConfigOpen(false)} />}
    </>
  )
}
