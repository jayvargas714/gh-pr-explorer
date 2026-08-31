import { useEffect, useState } from 'react'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'
import { useAutomationStore } from '../../stores/useAutomationStore'
import { ActiveConfigSummary } from './ActiveConfigSummary'
import { ScopeSection } from './ScopeSection'
import { ReviewerRegistrySection } from './ReviewerRegistrySection'
import { RoutingRulesSection } from './RoutingRulesSection'
import { AutoVerdictCriteriaSection } from './AutoVerdictCriteriaSection'

/** The master automation configuration tab: scope + repo allowlist, reviewer
 * registry, routing rules, and the relocated auto-verdict criteria. */
export function AutomationPanel() {
  const config = useAutomationStore((s) => s.config)
  const saving = useAutomationStore((s) => s.saving)
  const error = useAutomationStore((s) => s.error)
  const loaded = useAutomationStore((s) => s.loaded)
  const load = useAutomationStore((s) => s.load)
  const saveConfig = useAutomationStore((s) => s.saveConfig)

  const [draft, setDraft] = useState(config)
  const [dirty, setDirty] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    if (!loaded) load()
  }, [loaded, load])

  // Adopt the stored config until the operator starts editing.
  useEffect(() => {
    if (!dirty) setDraft(config)
  }, [config, dirty])

  const updateDraft = (next: typeof draft) => {
    setDraft(next)
    setDirty(true)
  }

  const handleSave = async () => {
    if (await saveConfig(draft)) {
      setDirty(false)
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 2000)
    }
  }

  return (
    <div className="mx-automation">
      <div className="mx-automation__header">
        <h2 className="mx-automation__title">🤖 Automation</h2>
        <div className="mx-automation__header-actions">
          {savedFlash && <span className="mx-automation__saved-flash">Saved ✓</span>}
          {dirty && <span className="mx-automation__dirty">unsaved changes</span>}
          <Button variant="primary" size="sm" onClick={handleSave} disabled={saving || !dirty}>
            {saving ? 'Saving…' : 'Save automation config'}
          </Button>
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      <ActiveConfigSummary />

      <ScopeSection draft={draft} setDraft={updateDraft} saving={saving} />
      <RoutingRulesSection draft={draft} setDraft={updateDraft} saving={saving} />
      <ReviewerRegistrySection />
      <AutoVerdictCriteriaSection />
    </div>
  )
}
