import { useEffect, useState } from 'react'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'
import { AutoVerdictCriteriaForm } from '../autoVerdict/AutoVerdictCriteriaForm'
import { useAutoVerdictStore } from '../../stores/useAutoVerdictStore'

/** The global auto-verdict criteria, relocated from the old header modal.
 * Storage and API are unchanged (/api/auto-verdict/config); per-PR overrides
 * still live on each card. */
export function AutoVerdictCriteriaSection() {
  const storedConfig = useAutoVerdictStore((s) => s.config)
  const saving = useAutoVerdictStore((s) => s.saving)
  const error = useAutoVerdictStore((s) => s.error)
  const save = useAutoVerdictStore((s) => s.save)

  const [draft, setDraft] = useState(storedConfig)
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    setDraft(storedConfig)
  }, [storedConfig])

  const handleSave = async () => {
    if (await save(draft)) {
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 2000)
    }
  }

  return (
    <section className="mx-automation__section">
      <h3 className="mx-automation__section-title">Auto Verdict Criteria</h3>
      <p className="mx-automation__intro">
        When a review finishes on a PR armed with 🤖 Auto, these thresholds decide the
        verdict. Exceeding any limit posts <strong>changes requested</strong>; staying
        within all of them counts as a pass. Individual cards can override the thresholds
        from their 🤖 menu.
      </p>

      {error && <Alert variant="error">{error}</Alert>}

      <div className="mx-auto-verdict-config">
        <AutoVerdictCriteriaForm draft={draft} setDraft={setDraft} saving={saving} showMasterSwitch />
      </div>

      <div className="mx-automation__form-actions">
        {savedFlash && <span className="mx-automation__saved-flash">Saved ✓</span>}
        <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save criteria'}
        </Button>
      </div>
    </section>
  )
}
