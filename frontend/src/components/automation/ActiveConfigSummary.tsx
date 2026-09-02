import { useAutomationStore } from '../../stores/useAutomationStore'

const SCOPE_LABELS: Record<string, string> = {
  off: 'Off',
  authors: 'By author',
  all: 'All new PRs',
}

/** Read-only strip showing the SAVED (active) automation configuration —
 * what the pipeline is running with right now, as opposed to the unsaved
 * draft being edited in the sections below. */
export function ActiveConfigSummary() {
  const config = useAutomationStore((s) => s.config)
  const reviewers = useAutomationStore((s) => s.reviewers)

  const reviewerLabel = (key: string) =>
    reviewers.find((r) => r.key === key)?.label ?? key

  const on = config.scope !== 'off'
  const scopeText =
    config.scope === 'authors'
      ? `By author (${config.authors.join(', ') || 'no authors listed'})`
      : SCOPE_LABELS[config.scope]

  const routingText = config.rules.length
    ? config.rules.map((r) => `${r.name} → ${reviewerLabel(r.reviewerKey)}`).join(' · ')
    : 'no rules'

  const conditions = [
    config.requireCiPass ? 'CI must pass' : 'CI not required',
    config.requireBaseBranch ? `base ${config.requireBaseBranch} only` : 'any base branch',
    `≤ ${config.maxBehindBase} behind base`,
    'no drafts',
    `pipeline cap ${config.maxPipelineSize}`,
  ].join(' · ')

  return (
    <div className={`mx-automation__active ${on ? 'mx-automation__active--on' : ''}`}>
      <span className={`mx-automation__active-state ${on ? 'mx-automation__active-state--on' : ''}`}>
        {on ? '● ACTIVE' : '○ OFF'}
      </span>
      <dl className="mx-automation__active-facts">
        <div>
          <dt>Scope</dt>
          <dd>{scopeText}</dd>
        </div>
        <div>
          <dt>Repos</dt>
          <dd>{config.repoAllowlist.length ? config.repoAllowlist.join(', ') : 'none allowlisted'}</dd>
        </div>
        <div>
          <dt>Routing</dt>
          <dd>
            {routingText} · other files → {reviewerLabel(config.defaultRule.reviewerKey)}
            {config.ignorePatterns.length > 0 &&
              ` · ${config.ignorePatterns.length} ignore pattern${config.ignorePatterns.length === 1 ? '' : 's'}`}
          </dd>
        </div>
        <div>
          <dt>Conditions</dt>
          <dd>{conditions} · max {config.maxConcurrentAutoReviews} concurrent</dd>
        </div>
      </dl>
    </div>
  )
}
