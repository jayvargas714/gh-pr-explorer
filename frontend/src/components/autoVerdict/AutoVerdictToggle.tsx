import { useEffect, useRef, useState } from 'react'
import { setCardAutoVerdict } from '../../api/autoVerdict'
import {
  AutoVerdictCriteriaOverride,
  AutoVerdictMode,
  AutoVerdictReviewer,
  MergeQueueItem,
} from '../../api/types'
import { describeCriteria, useAutoVerdictStore } from '../../stores/useAutoVerdictStore'
import { useAutomationStore } from '../../stores/useAutomationStore'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { AutoVerdictConfigModal } from './AutoVerdictConfigModal'

interface AutoVerdictToggleProps {
  item: MergeQueueItem
  onRefresh: () => void
}

const MODES: { key: AutoVerdictMode; label: string; hint: string }[] = [
  {
    key: 'verdict',
    label: 'Verdict mode',
    hint: 'thresholds decide approve / request changes',
  },
  {
    key: 'comment',
    label: 'Comment mode',
    hint: 'every completed review posts its findings as a comment',
  },
]

export function AutoVerdictToggle({ item, onRefresh }: AutoVerdictToggleProps) {
  const serverArmed = item.autoVerdict?.enabled ?? false
  const serverReviewer = item.autoVerdict?.reviewerType ?? 'default'
  const serverMode = item.autoVerdict?.mode ?? 'verdict'
  const serverOverride = item.autoVerdict?.criteriaOverride ?? null
  const config = useAutoVerdictStore((s) => s.config)
  const reviewers = useAutomationStore((s) => s.reviewers)
  const applyAutoVerdictLocal = useSwimlaneStore((s) => s.applyAutoVerdictLocal)

  const [menuOpen, setMenuOpen] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  // What the user just asked for, held until the server's copy agrees. Without
  // it the button can't change until onRefresh() has refetched the whole board
  // (a `gh pr view` per queued PR), which reads as the toggle being broken.
  const [pending, setPending] = useState<{
    enabled: boolean
    reviewerType: AutoVerdictReviewer
    mode: AutoVerdictMode
  } | null>(null)
  // Same optimistic hold for a just-saved criteria override (undefined = defer
  // to the server's copy). Cleared whenever the server value changes.
  const [pendingOverride, setPendingOverride] = useState<
    AutoVerdictCriteriaOverride | null | undefined
  >(undefined)
  const wrapperRef = useRef<HTMLDivElement>(null)

  const armed = pending?.enabled ?? serverArmed
  const reviewerType = pending?.reviewerType ?? serverReviewer
  const mode = pending?.mode ?? serverMode
  const override = pendingOverride !== undefined ? pendingOverride : serverOverride

  // Drop the optimistic value once the refreshed card carries it.
  useEffect(() => {
    if (!pending) return
    if (
      pending.enabled === serverArmed &&
      pending.reviewerType === serverReviewer &&
      pending.mode === serverMode
    ) {
      setPending(null)
    }
  }, [pending, serverArmed, serverReviewer, serverMode])

  const serverOverrideKey = JSON.stringify(serverOverride)
  useEffect(() => {
    setPendingOverride(undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverOverrideKey])

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

  const persist = async (
    enabled: boolean,
    reviewer: AutoVerdictReviewer,
    nextMode: AutoVerdictMode
  ) => {
    setPending({ enabled, reviewerType: reviewer, mode: nextMode })
    // Patch the board's own copy too, so the header's auto/manual counts and
    // the auto-mode filter move with the button. No-op outside the swimlane.
    applyAutoVerdictLocal(item.number, item.repo, {
      enabled,
      reviewerType: reviewer,
      mode: nextMode,
    })
    setBusy(true)
    try {
      await setCardAutoVerdict(item.number, item.repo, {
        enabled,
        reviewerType: reviewer,
        mode: nextMode,
      })
      onRefresh()
    } catch (err) {
      console.error('Failed to update auto verdict:', err)
      // Roll the optimistic state back to what the server still believes.
      setPending(null)
      applyAutoVerdictLocal(item.number, item.repo, {
        enabled: serverArmed,
        reviewerType: serverReviewer,
        mode: serverMode,
      })
    } finally {
      setBusy(false)
    }
  }

  // What the evaluator will actually use: the global config with this card's
  // override layered over it (the master switch stays global).
  const effectiveConfig = override ? { ...config, ...override } : config
  const criteriaText =
    mode === 'comment'
      ? 'comment mode — every completed review posts its findings as a comment'
      : describeCriteria(effectiveConfig)

  const modeIcon = mode === 'comment' ? '💬' : '🤖'
  const tooltip = armed
    ? `Auto ${mode} armed (${reviewers.find((r) => r.key === reviewerType)?.label ?? reviewerType}) — ${criteriaText}`
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
          {modeIcon} Auto{armed ? ' ✓' : ''}
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
                persist(!armed, reviewerType, mode)
                setMenuOpen(false)
              }}
            >
              {armed
                ? `⏹ Disarm auto ${mode}`
                : `▶ Arm auto ${mode}`}
            </button>

            <div className="mx-auto-verdict-menu__section">
              <span className="mx-auto-verdict-menu__label">Mode</span>
              <div role="radiogroup" aria-label="Auto mode">
                {MODES.map(({ key, label, hint }) => (
                  <button
                    key={key}
                    type="button"
                    role="radio"
                    aria-checked={mode === key}
                    className={`mx-auto-verdict-menu__reviewer${mode === key ? ' mx-auto-verdict-menu__reviewer--active' : ''}`}
                    disabled={busy}
                    onClick={() => persist(armed, reviewerType, key)}
                  >
                    <strong>{key === 'comment' ? '💬' : '🤖'} {label}</strong>
                    <small>{hint}</small>
                  </button>
                ))}
              </div>
            </div>

            <div className="mx-auto-verdict-menu__section">
              <span className="mx-auto-verdict-menu__label">Review agent</span>
              <div role="radiogroup" aria-label="Reviewer agent">
                {reviewers.map(({ key, label, agentName: agent }) => (
                  <button
                    key={key}
                    type="button"
                    role="radio"
                    aria-checked={reviewerType === key}
                    className={`mx-auto-verdict-menu__reviewer${reviewerType === key ? ' mx-auto-verdict-menu__reviewer--active' : ''}`}
                    disabled={busy}
                    onClick={() => persist(armed, key, mode)}
                  >
                    <strong>{label}</strong>
                    <small>{agent}</small>
                  </button>
                ))}
              </div>
            </div>

            <div className="mx-auto-verdict-menu__section">
              <span className="mx-auto-verdict-menu__criteria">
                {override && <span className="mx-auto-verdict-menu__override-chip">overridden</span>}
                {criteriaText}
              </span>
              <button
                type="button"
                className="mx-auto-verdict-menu__link"
                onClick={() => {
                  setMenuOpen(false)
                  setOverrideOpen(true)
                }}
              >
                {override ? 'Edit override for this PR…' : 'Override for this PR…'}
              </button>
              <button
                type="button"
                className="mx-auto-verdict-menu__link"
                onClick={() => {
                  setMenuOpen(false)
                  setConfigOpen(true)
                }}
              >
                Edit global criteria…
              </button>
            </div>
          </div>
        )}
      </div>

      {configOpen && <AutoVerdictConfigModal onClose={() => setConfigOpen(false)} />}
      {overrideOpen && (
        <AutoVerdictConfigModal
          onClose={() => setOverrideOpen(false)}
          perPR={{
            prNumber: item.number,
            repo: item.repo,
            override,
            onSaved: (saved) => {
              setPendingOverride(saved)
              onRefresh()
            },
          }}
        />
      )}
    </>
  )
}
