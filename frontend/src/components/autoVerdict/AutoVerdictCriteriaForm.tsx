import { Toggle } from '../common/Toggle'
import { AutoVerdictConfig } from '../../api/types'

const THRESHOLDS: { key: keyof AutoVerdictConfig; label: string; hint: string; min?: number }[] = [
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
  {
    key: 'mediationDisputedThreshold',
    label: 'Disputed critical/major → mediation at',
    hint: 'Disputed and deferred findings never count toward the limits above. At this many '
      + 'disputed critical/major findings the review is posted as a comment, auto verdict is '
      + 'disarmed, and the PR is routed to a human.',
    min: 1,
  },
]

interface AutoVerdictCriteriaFormProps {
  draft: AutoVerdictConfig
  setDraft: (draft: AutoVerdictConfig) => void
  saving: boolean
  // The master switch is global-only; per-PR overrides hide it.
  showMasterSwitch: boolean
}

/** The auto-verdict criteria fields, shared by the global Automation tab
 * section and the per-PR override modal. */
export function AutoVerdictCriteriaForm({
  draft,
  setDraft,
  saving,
  showMasterSwitch,
}: AutoVerdictCriteriaFormProps) {
  const setNumber = (key: keyof AutoVerdictConfig, raw: string) => {
    const parsed = parseInt(raw, 10)
    setDraft({ ...draft, [key]: Number.isNaN(parsed) || parsed < 0 ? 0 : parsed })
  }

  return (
    <>
      {showMasterSwitch && (
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
        {THRESHOLDS.map(({ key, label, hint, min }) => (
          <div className="mx-auto-verdict-config__field" key={key}>
            <label htmlFor={`av-${key}`}>{label}</label>
            <input
              id={`av-${key}`}
              type="number"
              min={min ?? 0}
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
    </>
  )
}
