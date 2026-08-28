import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { Toggle } from '../common/Toggle'
import { Alert } from '../common/Alert'
import { setCardAutoVerdictCriteria } from '../../api/autoVerdict'
import { useAutoVerdictStore } from '../../stores/useAutoVerdictStore'
import { AutoVerdictConfig, AutoVerdictCriteriaOverride } from '../../api/types'

interface PerPRProps {
  prNumber: number
  repo: string
  override: AutoVerdictCriteriaOverride | null
  onSaved: (override: AutoVerdictCriteriaOverride | null) => void
}

interface AutoVerdictConfigModalProps {
  onClose: () => void
  // When set, the modal edits this PR's criteria override instead of the
  // global config: the master switch is hidden (it is never per-PR) and a
  // "Use defaults" action clears the override.
  perPR?: PerPRProps
}

const THRESHOLDS: { key: keyof AutoVerdictConfig; label: string; hint: string }[] = [
  {
    key: 'maxCritical',
    label: 'Critical issues allowed',
    hint: '0 means a single critical issue triggers changes-requested.',
  },
  {
    key: 'maxMajor',
    label: 'Major issues allowed',
    hint: 'Usually 0, sometimes 1.',
  },
  {
    key: 'maxMinor',
    label: 'Minor issues allowed',
    hint: '99 is effectively unlimited — minors alone will not block.',
  },
]

export function AutoVerdictConfigModal({ onClose, perPR }: AutoVerdictConfigModalProps) {
  const storedConfig = useAutoVerdictStore((s) => s.config)
  const storeSaving = useAutoVerdictStore((s) => s.saving)
  const storeError = useAutoVerdictStore((s) => s.error)
  const save = useAutoVerdictStore((s) => s.save)

  const [draft, setDraft] = useState<AutoVerdictConfig>({
    ...storedConfig,
    ...(perPR?.override ?? {}),
  })
  const [perPRSaving, setPerPRSaving] = useState(false)
  const [perPRError, setPerPRError] = useState<string | null>(null)

  const saving = perPR ? perPRSaving : storeSaving
  const error = perPR ? perPRError : storeError

  // Adopt the stored config if it loads while the modal is already open.
  useEffect(() => {
    setDraft({ ...storedConfig, ...(perPR?.override ?? {}) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storedConfig])

  const setNumber = (key: keyof AutoVerdictConfig, raw: string) => {
    const parsed = parseInt(raw, 10)
    setDraft({ ...draft, [key]: Number.isNaN(parsed) || parsed < 0 ? 0 : parsed })
  }

  const persistOverride = async (override: AutoVerdictCriteriaOverride | null) => {
    if (!perPR) return
    setPerPRSaving(true)
    setPerPRError(null)
    try {
      await setCardAutoVerdictCriteria(perPR.prNumber, perPR.repo, override)
      perPR.onSaved(override)
      onClose()
    } catch (err) {
      setPerPRError(err instanceof Error ? err.message : 'Failed to save criteria override')
    } finally {
      setPerPRSaving(false)
    }
  }

  const handleSave = async () => {
    if (perPR) {
      const { enabled: _enabled, ...override } = draft
      await persistOverride(override)
    } else if (await save(draft)) {
      onClose()
    }
  }

  // Portal to body so the fixed-position overlay centers on the viewport. Both
  // call sites sit inside an ancestor that creates a containing block for fixed
  // descendants — the header's backdrop-filter, and the swimlane board — which
  // would otherwise pin the overlay to that box and clip it off-screen.
  return createPortal(
    <Modal
      title={perPR ? `Auto Verdict Criteria — PR #${perPR.prNumber}` : 'Auto Verdict Criteria'}
      onClose={onClose}
      size="md"
    >
      <div className="mx-auto-verdict-config">
        {error && <Alert variant="error">{error}</Alert>}

        <p className="mx-auto-verdict-config__intro">
          {perPR ? (
            <>
              These values override the global criteria for this PR only. The global
              master switch still gates all posting — while it is off, nothing posts.
            </>
          ) : (
            <>
              When a review finishes on a PR armed with 🤖 Auto, these thresholds decide the
              verdict. Exceeding any limit posts <strong>changes requested</strong>; staying
              within all of them counts as a pass.
            </>
          )}
        </p>

        {!perPR && (
          <div className="mx-auto-verdict-config__switches">
            <Toggle
              checked={draft.enabled}
              onChange={(enabled) => setDraft({ ...draft, enabled })}
              label="Auto verdicts enabled"
              disabled={saving}
            />
            <small className="mx-auto-verdict-config__hint">
              Master switch. While off, armed cards are evaluated for nothing and no verdict
              is ever posted.
            </small>
          </div>
        )}

        <div className="mx-auto-verdict-config__thresholds">
          {THRESHOLDS.map(({ key, label, hint }) => (
            <div className="mx-auto-verdict-config__field" key={key}>
              <label htmlFor={`av-${key}`}>{label}</label>
              <input
                id={`av-${key}`}
                type="number"
                min={0}
                value={draft[key] as number}
                onChange={(e) => setNumber(key, e.target.value)}
                disabled={saving}
                className="mx-auto-verdict-config__number"
              />
              <small className="mx-auto-verdict-config__hint">{hint}</small>
            </div>
          ))}
        </div>

        <div className="mx-auto-verdict-config__switches">
          <Toggle
            checked={draft.allowAutoApprove}
            onChange={(allowAutoApprove) => setDraft({ ...draft, allowAutoApprove })}
            label="Allow auto approvals"
            disabled={saving}
          />
          <small className="mx-auto-verdict-config__hint">
            Off means changes-requested only: a passing review posts nothing and the card
            shows <em>passed — approve manually</em> so every approval stays yours.
          </small>
        </div>

        <div className="mx-auto-verdict-config__switches">
          <Toggle
            checked={draft.autoFollowupReview}
            onChange={(autoFollowupReview) => setDraft({ ...draft, autoFollowupReview })}
            label="Auto follow-up review on new commits"
            disabled={saving}
          />
          <small className="mx-auto-verdict-config__hint">
            When an armed PR gets new commits after a review, a follow-up review starts
            automatically with the card's armed reviewer. Independent of the master
            switch — it starts reviews but never posts anything itself.
          </small>
        </div>

        <div className="mx-auto-verdict-config__actions">
          {perPR && perPR.override && (
            <Button variant="ghost" onClick={() => persistOverride(null)} disabled={saving}>
              Use defaults
            </Button>
          )}
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
    </Modal>,
    document.body
  )
}
