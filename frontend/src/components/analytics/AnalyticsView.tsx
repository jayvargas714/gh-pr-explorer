import { useState } from 'react'
import { useUIStore } from '../../stores/useUIStore'
import { StatsView } from './StatsView'
import { LifecycleView } from './LifecycleView'
import { ActivityView } from './ActivityView'
import { ResponsivenessView } from './ResponsivenessView'

export function AnalyticsView() {
  const { activeAnalyticsTab, setActiveAnalyticsTab } = useUIStore()

  const tabs = [
    { id: 'stats' as const, label: 'Stats', icon: '📊' },
    { id: 'lifecycle' as const, label: 'Lifecycle', icon: '🔄' },
    { id: 'activity' as const, label: 'Activity', icon: '📈' },
    { id: 'responsiveness' as const, label: 'Reviews', icon: '⏱️' },
  ]

  const renderContent = () => {
    switch (activeAnalyticsTab) {
      case 'stats':
        return <StatsView />
      case 'lifecycle':
        return <LifecycleView />
      case 'activity':
        return <ActivityView />
      case 'responsiveness':
        return <ResponsivenessView />
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

      <div className="mx-analytics__content">{renderContent()}</div>
    </div>
  )
}
