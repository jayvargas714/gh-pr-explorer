import { useUIStore } from '../../stores/useUIStore'

export function ViewTabs() {
  const { activeView, setActiveView } = useUIStore()

  const tabs = [
    { id: 'prs' as const, label: 'Pull Requests', icon: '🔀' },
    { id: 'analytics' as const, label: 'Analytics', icon: '📊' },
    { id: 'workflows' as const, label: 'CI/Workflows', icon: '⚙️' },
    { id: 'engine' as const, label: 'Review Workflows', icon: '🔬' },
  ]

  return (
    <div className="mx-view-tabs">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`mx-view-tab ${activeView === tab.id ? 'mx-view-tab--active' : ''}`}
          onClick={() => setActiveView(tab.id)}
        >
          <span className="mx-view-tab__icon">{tab.icon}</span>
          <span className="mx-view-tab__label">{tab.label}</span>
        </button>
      ))}
    </div>
  )
}
