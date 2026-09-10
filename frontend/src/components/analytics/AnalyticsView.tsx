import { useUIStore } from '../../stores/useUIStore'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { useAnalyticsDaily } from '../../hooks/useAnalyticsDaily'
import { WindowPicker } from './WindowPicker'
import { StatsView } from './StatsView'
import { ActivityView } from './ActivityView'
import { ContributorsView } from './ContributorsView'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

export function AnalyticsView() {
  const { activeAnalyticsTab, setActiveAnalyticsTab } = useUIStore()
  const { rangeError, isStale } = useAnalyticsDaily()
  const { window, setWindow, base, setBase, daily, dailyLoading, dailyError } = useAnalyticsStore()

  const tabs = [
    { id: 'stats' as const, label: 'Stats', icon: '📊' },
    { id: 'activity' as const, label: 'Activity', icon: '📈' },
    { id: 'contributors' as const, label: 'Contributors', icon: '👥' },
  ]

  const renderContent = () => {
    switch (activeAnalyticsTab) {
      case 'stats':
        return <StatsView />
      case 'activity':
        return <ActivityView />
      case 'contributors':
        return <ContributorsView />
      default:
        return null
    }
  }

  return (
    <div className="mx-analytics">
      <div className="mx-analytics__tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`mx-analytics-tab ${
              activeAnalyticsTab === tab.id ? 'mx-analytics-tab--active' : ''
            }`}
            onClick={() => setActiveAnalyticsTab(tab.id)}
          >
            <span className="mx-analytics-tab__icon">{tab.icon}</span>
            <span className="mx-analytics-tab__label">{tab.label}</span>
          </button>
        ))}
      </div>

      <WindowPicker
        window={window}
        onWindowChange={setWindow}
        base={base}
        baseOptions={daily?.base_branches ?? []}
        onBaseChange={setBase}
        rangeError={rangeError}
        lastUpdated={daily?.last_updated ?? null}
        syncing={daily?.syncing ?? false}
        refreshing={isStale || dailyLoading}
        earliest={daily?.coverage.earliest_pr_day}
        resolvedFrom={daily?.from}
        resolvedTo={daily?.to}
      />

      {dailyError && <Alert variant="error">{dailyError}</Alert>}
      {!dailyError && daily === null && dailyLoading && (
        <div className="mx-analytics__loading">
          <Spinner size="lg" />
        </div>
      )}
      {!dailyError && daily === null && !dailyLoading && (
        <p className="mx-analytics__hint">No data yet</p>
      )}
      {!dailyError && daily !== null && (
        <div className={`mx-analytics__content ${isStale ? 'mx-analytics__content--refreshing' : ''}`}>
          {renderContent()}
        </div>
      )}
    </div>
  )
}
