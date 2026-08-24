import { useEffect, useRef, useState } from 'react'
import { setCardAutoVerdict } from '../../api/autoVerdict'
import { AutoVerdictReviewer, MergeQueueItem } from '../../api/types'
import { describeCriteria, useAutoVerdictStore } from '../../stores/useAutoVerdictStore'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
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
  const serverArmed = item.autoVerdict?.enabled ?? false
  const serverReviewer = item.autoVerdict?.reviewerType ?? 'default'
  const config = useAutoVerdictStore((s) => s.config)
  const applyAutoVerdictLocal = useSwimlaneStore((s) => s.applyAutoVerdictLocal)

  const [menuOpen, setMenuOpen] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  // What the user just asked for, held until the server's copy agrees. Without
  // it the button can't change until onRefresh() has refetched the whole board
  // (a `gh pr view` per queued PR), which reads as the toggle being broken.
  const [pending, setPending] = useState<{
    enabled: boolean
    reviewerType: AutoVerdictReviewer
  } | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  const armed = pending?.enabled ?? serverArmed
  const reviewerType = pending?.reviewerType ?? serverReviewer

  // Drop the optimistic value once the refreshed card carries it.
  useEffect(() => {
    if (!pending) return
    if (pending.enabled === serverArmed && pending.reviewerType === serverReviewer) {
      setPending(null)
    }
  }, [pending, serverArmed, serverReviewer])

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
    setPending({ enabled, reviewerType: reviewer })
    // Patch the board's own copy too, so the header's auto/manual counts and
    // the auto-mode filter move with the button. No-op outside the swimlane.
    applyAutoVerdictLocal(item.number, item.repo, { enabled, reviewerType: reviewer })
    setBusy(true)
    try {
      await setCardAutoVerdict(item.number, item.repo, { enabled, reviewerType: reviewer })
      onRefresh()
    } catch (err) {
      console.error('Failed to update auto verdict:', err)
      // Roll the optimistic state back to what the server still believes.
      setPending(null)
      applyAutoVerdictLocal(item.number, item.repo, {
        enabled: serverArmed,
        reviewerType: serverReviewer,
      })
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
