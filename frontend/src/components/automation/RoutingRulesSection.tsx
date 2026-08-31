import { AutomationConfig, AutomationRule, AutoVerdictMode } from '../../api/types'
import { Button } from '../common/Button'
import { Select } from '../common/Select'
import { Toggle } from '../common/Toggle'
import { useAutomationStore } from '../../stores/useAutomationStore'
import { ChipListEditor } from './ChipListEditor'

interface RoutingRulesSectionProps {
  draft: AutomationConfig
  setDraft: (draft: AutomationConfig) => void
  saving: boolean
}

const MODE_OPTIONS = [
  { value: 'verdict', label: 'Verdict (approve / changes-requested)' },
  { value: 'comment', label: 'Comment only' },
]

/** Ordered file-pattern routing rules, global ignore patterns, and the pinned
 * default rule. Matching: first rule (top-down) whose pattern matches a file
 * claims it; a PR whose files span rules — or mix a rule with unmatched
 * files — is flagged unidentified and not auto-reviewed. */
export function RoutingRulesSection({ draft, setDraft, saving }: RoutingRulesSectionProps) {
  const reviewers = useAutomationStore((s) => s.reviewers)
  const reviewerOptions = reviewers.map((r) => ({ value: r.key, label: `${r.label} (${r.key})` }))

  const setRule = (index: number, rule: AutomationRule) => {
    const rules = [...draft.rules]
    rules[index] = rule
    setDraft({ ...draft, rules })
  }

  const moveRule = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= draft.rules.length) return
    const rules = [...draft.rules]
    ;[rules[index], rules[target]] = [rules[target], rules[index]]
    setDraft({ ...draft, rules })
  }

  const removeRule = (index: number) => {
    setDraft({ ...draft, rules: draft.rules.filter((_, i) => i !== index) })
  }

  const addRule = () => {
    setDraft({
      ...draft,
      rules: [
        ...draft.rules,
        {
          name: `Rule ${draft.rules.length + 1}`,
          patterns: [],
          reviewerKey: reviewers[0]?.key ?? 'default',
          autoVerdict: false,
          autoVerdictMode: 'verdict',
        },
      ],
    })
  }

  const renderVerdictControls = (
    rule: { autoVerdict: boolean; autoVerdictMode: AutoVerdictMode },
    onChange: (updates: { autoVerdict?: boolean; autoVerdictMode?: AutoVerdictMode }) => void
  ) => (
    <div className="mx-automation__rule-verdict">
      <Toggle
        checked={rule.autoVerdict}
        onChange={(autoVerdict) => onChange({ autoVerdict })}
        label="Auto verdict"
        disabled={saving}
      />
      {rule.autoVerdict && (
        <Select
          options={MODE_OPTIONS}
          value={rule.autoVerdictMode}
          onChange={(e) => onChange({ autoVerdictMode: e.target.value as AutoVerdictMode })}
          disabled={saving}
        />
      )}
    </div>
  )

  return (
    <section className="mx-automation__section">
      <h3 className="mx-automation__section-title">Reviewer Routing Rules</h3>
      <p className="mx-automation__intro">
        A new PR's changed files decide its reviewer. Files matching an ignore pattern are
        skipped first. If every remaining file matches the same rule, that rule's reviewer
        runs; if no file matches any rule, the default reviewer runs; a mix is flagged
        <strong> unidentified</strong> — the PR still lands in the Auto lane, but no review
        starts until you route it manually. Globs match the full path or the file name;
        <code> *</code> also crosses <code>/</code>.
      </p>

      <div className="mx-automation__field">
        <label>Ignore patterns</label>
        <small className="mx-automation__hint">
          Files stripped before classification — e.g. index files touched by every PB/ED PR.
        </small>
        <ChipListEditor
          values={draft.ignorePatterns}
          onChange={(ignorePatterns) => setDraft({ ...draft, ignorePatterns })}
          placeholder="*PB-000-index*"
          disabled={saving}
          mono
        />
      </div>

      {draft.rules.map((rule, index) => (
        <div className="mx-automation__rule" key={index}>
          <div className="mx-automation__rule-header">
            <span className="mx-automation__rule-order">{index + 1}</span>
            <input
              type="text"
              className="mx-input mx-automation__rule-name"
              value={rule.name}
              placeholder="Rule name"
              onChange={(e) => setRule(index, { ...rule, name: e.target.value })}
              disabled={saving}
            />
            <Select
              options={reviewerOptions}
              value={rule.reviewerKey}
              onChange={(e) => setRule(index, { ...rule, reviewerKey: e.target.value })}
              disabled={saving}
            />
            <div className="mx-automation__rule-actions">
              <Button variant="ghost" size="sm" onClick={() => moveRule(index, -1)} disabled={saving || index === 0}>
                ↑
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => moveRule(index, 1)}
                disabled={saving || index === draft.rules.length - 1}
              >
                ↓
              </Button>
              <Button variant="ghost" size="sm" onClick={() => removeRule(index)} disabled={saving}>
                −
              </Button>
            </div>
          </div>
          <ChipListEditor
            values={rule.patterns}
            onChange={(patterns) => setRule(index, { ...rule, patterns })}
            placeholder="PB-[0-9]*"
            disabled={saving}
            mono
          />
          {renderVerdictControls(rule, (updates) => setRule(index, { ...rule, ...updates }))}
        </div>
      ))}

      <Button variant="ghost" size="sm" onClick={addRule} disabled={saving}>
        + Add Rule
      </Button>

      <div className="mx-automation__rule mx-automation__rule--default">
        <div className="mx-automation__rule-header">
          <span className="mx-automation__rule-order">✱</span>
          <span className="mx-automation__rule-name mx-automation__rule-name--fixed">
            Default (no rule matched)
          </span>
          <Select
            options={reviewerOptions}
            value={draft.defaultRule.reviewerKey}
            onChange={(e) =>
              setDraft({ ...draft, defaultRule: { ...draft.defaultRule, reviewerKey: e.target.value } })
            }
            disabled={saving}
          />
        </div>
        {renderVerdictControls(draft.defaultRule, (updates) =>
          setDraft({ ...draft, defaultRule: { ...draft.defaultRule, ...updates } })
        )}
      </div>
    </section>
  )
}
