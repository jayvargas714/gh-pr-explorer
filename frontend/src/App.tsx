import { useEffect } from 'react'
import { MainLayout } from './components/layout/MainLayout'
import { ViewTabs } from './components/layout/ViewTabs'
import { WelcomeSection } from './components/layout/WelcomeSection'
import { AccountSelector } from './components/account/AccountSelector'
import { RepoSelector } from './components/account/RepoSelector'
import { FilterPanel } from './components/filters/FilterPanel'
import { PRList } from './components/prs/PRList'
import { AnalyticsView } from './components/analytics/AnalyticsView'
import { WorkflowsView } from './components/workflows/WorkflowsView'
import { RepoStatsView } from './components/repo-stats/RepoStatsView'
import { QueuePanel } from './components/queue/QueuePanel'
import { ReviewErrorModal } from './components/reviews/ReviewErrorModal'
import { ReviewViewer } from './components/reviews/ReviewViewer'
import { HistoryPanel } from './components/reviews/HistoryPanel'
import { ReviewPollingManager } from './components/reviews/ReviewPollingManager'
import { TimelineModal } from './components/timeline/TimelineModal'
import { SwimlaneModal } from './components/swimlane/SwimlaneModal'
import { TooltipProvider } from './components/common/Tooltip'
import { useAccountStore } from './stores/useAccountStore'
import { useUIStore } from './stores/useUIStore'
import { useQueueStore } from './stores/useQueueStore'
import { useSettingsPersistence } from './hooks/useSettingsPersistence'
import { fetchMergeQueue } from './api/queue'

function App() {
  const { selectedAccount, selectedRepo } = useAccountStore()
  const activeView = useUIStore((state) => state.activeView)
  const setMergeQueue = useQueueStore((state) => state.setMergeQueue)

  useSettingsPersistence()

  useEffect(() => {
    // Check for saved theme preference or default to dark
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme === 'light') {
      document.documentElement.classList.add('matrix-light')
    }
  }, [])

  useEffect(() => {
    // Load the merge queue once on startup so PR-list queue buttons and the
    // header count reflect real membership before the queue panel is opened.
    fetchMergeQueue()
      .then((response) => setMergeQueue(response.queue))
      .catch((err) => console.error('Initial queue load failed:', err))
  }, [setMergeQueue])

  const renderView = () => {
    if (!selectedRepo) return null

    switch (activeView) {
      case 'prs':
        return <PRList />
      case 'analytics':
        return <AnalyticsView />
      case 'workflows':
        return <WorkflowsView />
      case 'repo-stats':
        return <RepoStatsView />
      default:
        return null
    }
  }

  return (
    <>
      <MainLayout>
        <AccountSelector />
        <RepoSelector />

        {!selectedAccount ? (
          <WelcomeSection />
        ) : !selectedRepo ? (
          <div className="mx-empty-state">
            <h2>Select a Repository</h2>
            <p>Choose a repository from the dropdown above to view pull requests</p>
          </div>
        ) : (
          <>
            <ViewTabs />
            <FilterPanel />
            {renderView()}
          </>
        )}
      </MainLayout>

      <QueuePanel />
      <HistoryPanel />
      <ReviewErrorModal />
      <ReviewViewer />
      <ReviewPollingManager />
      <TimelineModal />
      <SwimlaneModal />
      <TooltipProvider />
    </>
  )
}

export default App
