import { AutomationConfig, AutomationScope } from '../../api/types'
import { ChipListEditor } from './ChipListEditor'

const SCOPES: { value: AutomationScope; label: string; hint: string }[] = [
  { value: 'off', label: 'Off', hint: 'No PRs are auto-processed.' },
  { value: 'authors', label: 'By author', hint: 'Only new PRs from the listed authors.' },
  { value: 'all', label: 'All new PRs', hint: 'Every new PR in an allowlisted repo.' },
]

interface ScopeSectionProps {
  draft: AutomationConfig
  setDraft: (draft: AutomationConfig) => void
  saving: boolean
}

/** Master automation scope: off / by-author / all, plus repo allowlist and
 * concurrency limit. Only PRs first seen AFTER enabling are processed. */
export function ScopeSection({ draft, setDraft, saving }: ScopeSectionProps) {
  return (
    <section className="mx-automation__section">
      <h3 className="mx-automation__section-title">Full Automation</h3>
      <p className="mx-automation__intro">
        When enabled, newly arriving PRs in allowlisted repos are classified by the routing
        rules below, added to the <strong>Auto</strong> swimlane, and reviewed automatically.
        Only PRs first seen after enabling are picked up — existing PRs are never swept.
      </p>

      <div className="mx-automation__scope-options" role="radiogroup" aria-label="Automation scope">
        {SCOPES.map(({ value, label, hint }) => (
          <label
            key={value}
            className={`mx-automation__scope-option ${draft.scope === value ? 'mx-automation__scope-option--active' : ''}`}
          >
            <input
              type="radio"
              name="automation-scope"
              value={value}
              checked={draft.scope === value}
              onChange={() => setDraft({ ...draft, scope: value })}
              disabled={saving}
            />
            <span className="mx-automation__scope-label">{label}</span>
            <small className="mx-automation__hint">{hint}</small>
          </label>
        ))}
      </div>

      {draft.scope === 'authors' && (
        <div className="mx-automation__field">
          <label>Authors</label>
          <small className="mx-automation__hint">
            GitHub logins whose new PRs are auto-processed.
          </small>
          <ChipListEditor
            values={draft.authors}
            onChange={(authors) => setDraft({ ...draft, authors })}
            placeholder="github-login"
            disabled={saving}
          />
        </div>
      )}

      <div className="mx-automation__field">
        <label>Repository allowlist</label>
        <small className="mx-automation__hint">
          Automation only touches PRs in these repos. Empty list means nothing is processed.
        </small>
        <ChipListEditor
          values={draft.repoAllowlist}
          onChange={(repoAllowlist) => setDraft({ ...draft, repoAllowlist })}
          placeholder="owner/repo"
          disabled={saving}
          mono
        />
      </div>

      <div className="mx-automation__field mx-automation__field--inline">
        <label htmlFor="automation-concurrency">Max concurrent auto reviews</label>
        <input
          id="automation-concurrency"
          type="number"
          min={1}
          className="mx-automation__number"
          value={draft.maxConcurrentAutoReviews}
          onChange={(e) => {
            const parsed = parseInt(e.target.value, 10)
            setDraft({
              ...draft,
              maxConcurrentAutoReviews: Number.isNaN(parsed) || parsed < 1 ? 1 : parsed,
            })
          }}
          disabled={saving}
        />
        <small className="mx-automation__hint">
          Caps how many auto-started reviews run at once; extra PRs wait their turn.
        </small>
      </div>
    </section>
  )
}
