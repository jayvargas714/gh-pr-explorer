import { useEffect, useState } from 'react'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { Toggle } from '../common/Toggle'
import { Alert } from '../common/Alert'
import { useAutoVerdictStore } from '../../stores/useAutoVerdictStore'
import { AutoVerdictConfig } from '../../api/types'

interface AutoVerdictConfigModalProps {
  onClose: () => void
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

export function AutoVerdictConfigModal({ onClose }: AutoVerdictConfigModalProps) {
  const storedConfig = useAutoVerdictStore((s) => s.config)
  const saving = useAutoVerdictStore((s) => s.saving)
  const storeError = useAutoVerdictStore((s) => s.error)
  const save = useAutoVerdictStore((s) => s.save)

  const [draft, setDraft] = useState<AutoVerdictConfig>(storedConfig)

  // Adopt the stored config if it loads while the modal is already open.
  useEffect(() => {
    setDraft(storedConfig)
  }, [storedConfig])

  const setNumber = (key: keyof AutoVerdictConfig, raw: string) => {
    const parsed = parseInt(raw, 10)
    setDraft({ ...draft, [key]: Number.isNaN(parsed) || parsed < 0 ? 0 : parsed })
  }

  const handleSave = async () => {
    if (await save(draft)) onClose()
  }

  return (
    <Modal title="Auto Verdict Criteria" onClose={onClose} size="md">
      <div className="mx-auto-verdict-config">
        {storeError && <Alert variant="error">{storeError}</Alert>}

        <p className="mx-auto-verdict-config__intro">
          When a review finishes on a PR armed with 🤖 Auto, these thresholds decide the
          verdict. Exceeding any limit posts <strong>changes requested</strong>; staying
          within all of them counts as a pass.
        </p>

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

        <div className="mx-auto-verdict-config__actions">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
