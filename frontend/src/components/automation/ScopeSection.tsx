import { AutomationConfig, AutomationScope } from '../../api/types'
import { Toggle } from '../common/Toggle'
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

      <div className="mx-automation__field">
        <label>Dispatch conditions</label>
        <small className="mx-automation__hint">
          A detected PR waits in the Auto lane (⏳ badge) until every condition holds,
          then its review starts. Draft PRs always wait until marked ready.
        </small>

        <div className="mx-automation__field mx-automation__field--inline">
          <Toggle
            checked={draft.requireCiPass}
            onChange={(requireCiPass) => setDraft({ ...draft, requireCiPass })}
            label="Require CI to complete and pass"
            disabled={saving}
          />
          <small className="mx-automation__hint">
            PRs with no CI checks at all are not held up.
          </small>
        </div>

        <div className="mx-automation__field mx-automation__field--inline">
          <label htmlFor="automation-base-branch">Required base branch</label>
          <input
            id="automation-base-branch"
            type="text"
            className="mx-automation__number"
            value={draft.requireBaseBranch}
            onChange={(e) => setDraft({ ...draft, requireBaseBranch: e.target.value })}
            placeholder="any"
            disabled={saving}
          />
          <small className="mx-automation__hint">
            Only PRs targeting this branch for merge are dispatched; others wait
            (e.g. stacked PRs until retargeted). Leave empty to allow any base.
          </small>
        </div>

        <div className="mx-automation__field mx-automation__field--inline">
          <label htmlFor="automation-max-behind">Max commits behind base</label>
          <input
            id="automation-max-behind"
            type="number"
            min={0}
            className="mx-automation__number"
            value={draft.maxBehindBase}
            onChange={(e) => {
              const parsed = parseInt(e.target.value, 10)
              setDraft({ ...draft, maxBehindBase: Number.isNaN(parsed) || parsed < 0 ? 0 : parsed })
            }}
            disabled={saving}
          />
          <small className="mx-automation__hint">
            The PR branch must be within this many commits of its base branch head.
          </small>
        </div>

        <div className="mx-automation__field mx-automation__field--inline">
          <label htmlFor="automation-pipeline-size">Max pipeline size</label>
          <input
            id="automation-pipeline-size"
            type="number"
            min={1}
            className="mx-automation__number"
            value={draft.maxPipelineSize}
            onChange={(e) => {
              const parsed = parseInt(e.target.value, 10)
              setDraft({ ...draft, maxPipelineSize: Number.isNaN(parsed) || parsed < 1 ? 1 : parsed })
            }}
            disabled={saving}
          />
          <small className="mx-automation__hint">
            Open PRs wait in the pipeline until their conditions hold; at this many
            waiting PRs, new ones are not enrolled.
          </small>
        </div>
      </div>
    </section>
  )
}
